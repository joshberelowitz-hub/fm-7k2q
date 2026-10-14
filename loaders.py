"""
loaders.py — pulls public data. Every source is cached to data/*.csv; if a download
fails, the last cached copy is used and the failure is shown on the page.

Sources (all reachable from GitHub's servers, tested Oct 2026):
  IMF WEO .............. api.imf.org SDMX 3.0
  OECD monthly rates ... sdmx.oecd.org (10y yields, 3m interbank)
  US Treasury curve .... home.treasury.gov (daily)
  ACM term premium ..... newyorkfed.org (daily)
  UK 10y ............... Bank of England database (daily)
  Germany 10y .......... Bundesbank (daily)
  Japan curve .......... Ministry of Finance (daily)
  FX, DXY, MOVE ........ Yahoo Finance chart API
  US 10y breakeven ..... Treasury nominal minus real curve
"""
from __future__ import annotations

import datetime as dt
import io
import os
import time

import numpy as np
import pandas as pd
import requests

import config as C

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
TIMEOUT = (10, 60)
HEALTH: list[tuple[str, str, str]] = []


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _cached(name: str, fetch, dated: bool = True) -> pd.DataFrame | None:
    path = os.path.join(CACHE, f"{name}.csv")
    t0 = time.time()
    try:
        df = fetch()
        if df is None or len(df) == 0:
            raise ValueError("empty response")
        print(f"  ok   {name} ({time.time() - t0:.1f}s, {len(df)} rows)", flush=True)
        os.makedirs(CACHE, exist_ok=True)
        df.to_csv(path)
        last = str(df.index.max())[:10] if dated else ""
        HEALTH.append((name, "fresh", last))
        return df
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {name} ({time.time() - t0:.1f}s): {type(e).__name__}: {str(e)[:150]}", flush=True)
        if os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=dated)
            last = str(df.index.max())[:10] if dated else ""
            HEALTH.append((name, f"cached copy (download failed: {type(e).__name__})", last))
            return df
        HEALTH.append((name, f"FAILED: {type(e).__name__}: {str(e)[:80]}", ""))
        return None


def _series(df: pd.DataFrame | None) -> pd.Series | None:
    return None if df is None else df.iloc[:, 0].dropna()


# ---------------------------------------------------------------- IMF (SDMX 3.0)
def _imf_parse(j: dict) -> pd.DataFrame:
    d = j["data"]
    st = d["structures"][0]
    sdims = st["dimensions"]["series"]
    times = [v.get("value", v.get("id")) for v in st["dimensions"]["observation"][0]["values"]]
    ci = [x["id"] for x in sdims].index("COUNTRY")
    rows = []
    for key, s in d["dataSets"][0].get("series", {}).items():
        idx = [int(i) for i in key.split(":")]
        country = sdims[ci]["values"][idx[ci]]["id"]
        for t, obs in s.get("observations", {}).items():
            v = obs[0]
            if v not in (None, "", "NaN"):
                rows.append((country, int(times[int(t)]), float(v)))
    return pd.DataFrame(rows, columns=["iso3", "year", "value"])


def _imf(indicator: str, iso3s: list[str]) -> pd.DataFrame:
    base = "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/"
    try:
        df = _imf_parse(_get(base + f"{'+'.join(iso3s)}.{indicator}.A").json())
        if len(df):
            return df
    except Exception:  # noqa: BLE001
        pass
    parts = []
    for i in iso3s:  # fallback: one country at a time
        try:
            parts.append(_imf_parse(_get(base + f"{i}.{indicator}.A").json()))
        except Exception:  # noqa: BLE001
            continue
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def imf(key: str, iso3s: list[str]) -> pd.DataFrame | None:
    ind = C.IMF_INDICATORS[key]
    df = _cached(f"imf_{ind}", lambda: _imf(ind, iso3s), dated=False)
    if df is None:
        return None
    return df.pivot_table(index="year", columns="iso3", values="value")


# ---------------------------------------------------------------- OECD monthly
def _oecd() -> pd.DataFrame:
    iso = "+".join(C.ISO3[c] for c in C.COUNTRIES + C.FACTOR_EXTRA)
    url = ("https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_FINMARK,/"
           f"{iso}.M.IRLT+IR3TIB.PA.....?startPeriod=1990-01&format=csvfile")
    df = pd.read_csv(io.StringIO(_get(url).text))
    df = df[["REF_AREA", "MEASURE", "TIME_PERIOD", "OBS_VALUE"]].dropna()
    df["date"] = pd.to_datetime(df["TIME_PERIOD"])
    df["col"] = df["MEASURE"] + "_" + df["REF_AREA"]
    return df.pivot_table(index="date", columns="col", values="OBS_VALUE").sort_index()


# ---------------------------------------------------------------- daily sources
def _treasury() -> pd.DataFrame:
    parts = []
    for y in range(2006, dt.date.today().year + 1):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve"
               f"&field_tdr_date_value={y}&page&_format=csv")
        try:
            p = pd.read_csv(io.StringIO(_get(url).text))
            parts.append(p[["Date", "10 Yr", "30 Yr"]])
        except Exception:  # noqa: BLE001
            continue
    df = pd.concat(parts)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date").sort_index().rename(columns={"10 Yr": "US10Y", "30 Yr": "US30Y"})


def _treasury_real() -> pd.DataFrame:
    parts = []
    for y in range(2006, dt.date.today().year + 1):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{y}/all?type=daily_treasury_real_yield_curve"
               f"&field_tdr_date_value={y}&page&_format=csv")
        try:
            p = pd.read_csv(io.StringIO(_get(url).text))
            col = [c for c in p.columns if c.strip().upper() in ("10 YR", "10 YEAR")][0]
            parts.append(p[["Date", col]].rename(columns={col: "US10Y_REAL"}))
        except Exception:  # noqa: BLE001
            continue
    df = pd.concat(parts)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date").sort_index()


def _acm() -> pd.DataFrame:
    r = _get("https://www.newyorkfed.org/medialibrary/media/research/data_indicators/ACMTermPremium.xls")
    xl = pd.read_excel(io.BytesIO(r.content), sheet_name=None)
    for _, sh in xl.items():
        cols = {str(c).strip().upper(): c for c in sh.columns}
        if "ACMTP10" in cols:
            dcol = cols.get("DATE", sh.columns[0])
            out = sh[[dcol, cols["ACMTP10"]]].copy()
            out.columns = ["date", "US_TP_ACM"]
            out["date"] = pd.to_datetime(out["date"], errors="coerce", dayfirst=True)
            return out.dropna().set_index("date").sort_index()
    raise ValueError("ACMTP10 column not found")


def _boe() -> pd.DataFrame:
    url = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes"
           "&Datefrom=01/Jan/2006&Dateto=now&SeriesCodes=IUDMNPY&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
    df = pd.read_csv(io.StringIO(_get(url).text))
    df["DATE"] = pd.to_datetime(df["DATE"], format="%d %b %Y")
    return df.set_index("DATE").rename(columns={"IUDMNPY": "UK10Y"})


def _bbk() -> pd.DataFrame:
    url = ("https://api.statistiken.bundesbank.de/rest/data/BBSIS/"
           "D.I.ZAR.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?format=csv&startPeriod=2006-01-01")
    rows = []
    for line in _get(url).content.decode("utf-8-sig").splitlines():
        p = line.split(";")
        if len(p) >= 2 and len(p[0]) == 10 and p[0][4] == "-" and p[1] not in (".", ""):
            rows.append((pd.Timestamp(p[0]), float(p[1].replace(",", "."))))
    return pd.DataFrame(rows, columns=["date", "DE10Y"]).set_index("date")


def _mof() -> pd.DataFrame:
    base = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
    parts = []
    for f in ("historical/jgbcme_all.csv", "jgbcme.csv"):
        txt = _get(base + f).content.decode("utf-8", errors="ignore")
        p = pd.read_csv(io.StringIO(txt), skiprows=1)
        p = p[["Date", "10Y", "30Y"]]
        p["Date"] = pd.to_datetime(p["Date"], format="%Y/%m/%d", errors="coerce")
        parts.append(p.dropna(subset=["Date"]))
    df = pd.concat(parts).drop_duplicates("Date", keep="last").set_index("Date").sort_index()
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.loc["2006":].rename(columns={"10Y": "JP10Y", "30Y": "JP30Y"})


def _yahoo(ticker: str, name: str) -> pd.DataFrame:
    p2 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1=1136073600&period2={p2}&interval=1d")
    res = _get(url).json()["chart"]["result"][0]
    ts = pd.to_datetime(res["timestamp"], unit="s").normalize()
    close = res["indicators"]["quote"][0]["close"]
    df = pd.DataFrame({name: close}, index=ts).dropna()
    return df[~df.index.duplicated(keep="last")]


def _dbnomics(code: str, name: str) -> pd.DataFrame:
    j = _get(f"https://api.db.nomics.world/v22/series/{code}?observations=1").json()
    doc = j["series"]["docs"][0]
    df = pd.DataFrame({"date": pd.to_datetime(doc["period_start_day"]), name: doc["value"]})
    df[name] = pd.to_numeric(df[name], errors="coerce")
    return df.set_index("date").dropna()


# ---------------------------------------------------------------- CNBC (France/Italy 10y, live + weekly history)
CNBC_SYMBOLS = {"FR10Y": "FR10Y-FR", "IT10Y": "IT10Y-IT", "DE10Y_CNBC": "DE10Y-DE"}


def _cnbc() -> pd.DataFrame:
    import json
    cols = {}
    for name, sym in CNBC_SYMBOLS.items():
        bars = _get(f"https://ts-api.cnbc.com/harmony/app/charts/5Y.json?symbol={sym}").json()["barData"]["priceBars"]
        s = pd.Series({pd.Timestamp(b["tradeTime"][:8]): float(b["close"]) for b in bars})
        cols[name] = s
    q = _get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
             + "%7C".join(CNBC_SYMBOLS.values())
             + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json").json()
    for x in q["FormattedQuoteResult"]["FormattedQuote"]:
        name = {v: k for k, v in CNBC_SYMBOLS.items()}[x["symbol"]]
        t = pd.Timestamp(x["last_time"][:10])
        cols[name][t] = float(str(x["last"]).rstrip("%"))
    df = pd.DataFrame(cols).sort_index()
    return df[~df.index.duplicated(keep="last")]


# ---------------------------------------------------------------- zero curves for the ACM model
def _gsw() -> pd.DataFrame:
    txt = _get("https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv").text
    lines = txt.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("Date,"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), index_col=0, parse_dates=True)
    return df[["BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2"]].dropna()


def _bbk_zero(freq: str, start: str) -> pd.DataFrame:
    url = ("https://api.statistiken.bundesbank.de/rest/data/BBSIS/"
           f"{freq}.I.ZST.ZI.EUR.S1311.B.A604..R.A.A._Z._Z.A?format=csv&startPeriod={start}")
    lines = _get(url).content.decode("utf-8-sig").splitlines()
    codes = [h.split(".")[9] for h in lines[0].split(";")[1::2]]
    mats = [6 if c == "R005X" else int(c[1:3]) * 12 for c in codes]
    rows, idx = [], []
    for line in lines:
        p = line.split(";")
        if p and len(p[0]) in (7, 10) and p[0][4] == "-":
            idx.append(pd.Timestamp(p[0]))
            rows.append([np.nan if v in (".", "") else float(v.replace(",", ".")) for v in p[1::2]])
    return pd.DataFrame(rows, index=idx, columns=mats)


def _boe_zip(url: str, want: str) -> pd.DataFrame:
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(_get(url).content))
    parts = []
    for f in z.namelist():
        if want not in f:
            continue
        for sh in ("4. spot curve", "3. spot, short end"):
            df = pd.read_excel(z.open(f), sheet_name=sh, header=None)
            mats = [round(float(x) * 12) for x in df.iloc[3, 1:]]
            d = df.iloc[5:].copy()
            d = d[pd.to_datetime(d[0], errors="coerce").notna()]
            parts.append(pd.DataFrame(d.iloc[:, 1:].astype(float).values,
                                      index=pd.to_datetime(d[0]), columns=mats))
    out = pd.concat(parts, axis=1)
    out = out.T.groupby(level=0).first().T          # merge duplicate maturities (short end vs curve)
    return out.sort_index()[sorted(out.columns)]


def _mof_full() -> pd.DataFrame:
    base = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
    parts = []
    for f in ("historical/jgbcme_all.csv", "jgbcme.csv"):
        txt = _get(base + f).content.decode("utf-8", errors="ignore")
        p = pd.read_csv(io.StringIO(txt), skiprows=1, na_values=["-"])
        p["Date"] = pd.to_datetime(p["Date"], format="%Y/%m/%d", errors="coerce")
        parts.append(p.dropna(subset=["Date"]))
    df = pd.concat(parts).drop_duplicates("Date", keep="last").set_index("Date").sort_index()
    return df.apply(pd.to_numeric, errors="coerce").loc["1986":]


def _ecb_euribor1m() -> pd.DataFrame:
    url = "https://data-api.ecb.europa.eu/service/data/FM/M.U2.EUR.RT.MM.EURIBOR1MD_.HSTA?format=csvdata"
    df = pd.read_csv(io.StringIO(_get(url).text))
    return pd.DataFrame({"EURIBOR1M": df["OBS_VALUE"].values}, index=pd.to_datetime(df["TIME_PERIOD"]))


def load_curves() -> dict:
    from concurrent.futures import ThreadPoolExecutor
    boe = "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/"
    jobs = {
        "gsw": lambda: _cached("curve_us_gsw", _gsw),
        "de_m": lambda: _cached("curve_de_monthly", lambda: _bbk_zero("M", "1997-01")),
        "de_d": lambda: _cached("curve_de_daily", lambda: _bbk_zero("D", (dt.date.today() - dt.timedelta(days=45)).isoformat())),
        "uk_m": lambda: _cached("curve_uk_monthly", lambda: _boe_zip(boe + "glcnominalmonthedata.zip", "Nominal")),
        "uk_d": lambda: _cached("curve_uk_daily", lambda: _boe_zip(boe + "latest-yield-curve-data.zip", "GLC Nominal daily")),
        "jp": lambda: _cached("curve_jp_mof", _mof_full),
        "euribor": lambda: _cached("euribor1m", _ecb_euribor1m),
    }
    with ThreadPoolExecutor(max_workers=7) as ex:
        futs = {k: ex.submit(f) for k, f in jobs.items()}
        return {k: f.result() for k, f in futs.items()}


# ---------------------------------------------------------------- all
def load_all() -> dict:
    from concurrent.futures import ThreadPoolExecutor
    iso_all = sorted({C.ISO3[c] for c in C.COUNTRIES})
    jobs = {
        "oecd": lambda: _cached("oecd_rates", _oecd),
        "ust": lambda: _cached("ust_curve", _treasury),
        "acm": lambda: _cached("acm_tp", _acm),
        "boe": lambda: _cached("boe_10y", _boe),
        "bbk": lambda: _cached("bbk_10y", _bbk),
        "mof": lambda: _cached("mof_jgb", _mof),
        "dxy": lambda: _cached("yahoo_DXY", lambda: _yahoo("DX-Y.NYB", "USD_BROAD")),
        "jpy": lambda: _cached("yahoo_JPY", lambda: _yahoo("JPY=X", "JPY_PER_USD")),
        "eur": lambda: _cached("yahoo_EURUSD", lambda: _yahoo("EURUSD=X", "USD_PER_EUR")),
        "gbp": lambda: _cached("yahoo_GBPUSD", lambda: _yahoo("GBPUSD=X", "USD_PER_GBP")),
        "move": lambda: _cached("yahoo_MOVE", lambda: _yahoo("^MOVE", "MOVE")),
        "real": lambda: _cached("ust_real_curve", _treasury_real),
        "cnbc": lambda: _cached("cnbc_fr_it_10y", _cnbc),
    }
    for k in C.IMF_INDICATORS:
        jobs[f"imf_{k}"] = (lambda k=k: imf(k, iso_all))
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {k: ex.submit(f) for k, f in jobs.items()}
        res = {k: f.result() for k, f in futs.items()}

    oecd = res["oecd"]
    y10 = s3m = pd.DataFrame()
    if oecd is not None:
        allc = C.COUNTRIES + C.FACTOR_EXTRA
        y10 = pd.DataFrame({c: oecd[f"IRLT_{C.ISO3[c]}"] for c in allc if f"IRLT_{C.ISO3[c]}" in oecd})
        s3m = pd.DataFrame({c: oecd[f"IR3TIB_{C.ISO3[c]}"] for c in allc if f"IR3TIB_{C.ISO3[c]}" in oecd})
    daily_parts = [res[k] for k in ("ust", "real", "acm", "boe", "bbk", "mof", "dxy", "jpy", "eur", "gbp", "cnbc")
                   if res[k] is not None]
    daily = pd.concat(daily_parts, axis=1).sort_index() if daily_parts else pd.DataFrame()
    daily = daily.apply(pd.to_numeric, errors="coerce")
    if {"US10Y", "US10Y_REAL"} <= set(daily.columns):
        daily["US_BE10"] = daily["US10Y"] - daily["US10Y_REAL"]
    imf_data = {k: res[f"imf_{k}"] for k in C.IMF_INDICATORS}
    move = _series(res["move"])
    curves = load_curves()
    if oecd is not None:
        y10.attrs["oecd"] = oecd
    return {"y10": y10, "s3m": s3m, "daily": daily, "imf": imf_data, "move": move, "curves": curves}


# ---------------------------------------------------------------- mock (for testing)
def mock_all(seed: int = 1) -> dict:
    rng = np.random.default_rng(seed)
    allc = C.COUNTRIES + C.FACTOR_EXTRA
    m = pd.date_range("1995-01-01", "2026-09-01", freq="MS")
    common = np.cumsum(rng.normal(0, 0.12, len(m))) * 0.5 + 3
    s3m = pd.DataFrame({c: np.clip(common - 1 + np.cumsum(rng.normal(0, 0.05, len(m))), -0.7, None)
                        for c in allc}, index=m)
    y10 = pd.DataFrame({c: s3m[c] + 1.0 + rng.normal(0, 0.2, len(m)) for c in allc}, index=m)
    y10.loc["2011-08":"2012-06", "IT"] += 3
    y10.loc["2022-09", "UK"] += 1.2
    y10.loc["2024-06":, "FR"] += 0.7
    d = pd.date_range("2006-01-01", "2026-10-13", freq="B")
    daily = pd.DataFrame({
        "US10Y": 3 + np.cumsum(rng.normal(0, 0.04, len(d))) * 0.3,
        "US30Y": 3.5 + np.cumsum(rng.normal(0, 0.04, len(d))) * 0.3,
        "US_TP_ACM": 0.5 + np.cumsum(rng.normal(0, 0.02, len(d))) * 0.3,
        "USD_BROAD": 110 + np.cumsum(rng.normal(0, 0.3, len(d))),
        "JPY_PER_USD": 120 + np.cumsum(rng.normal(0, 0.5, len(d))),
        "USD_PER_EUR": 1.15 + np.cumsum(rng.normal(0, 0.004, len(d))),
        "USD_PER_GBP": 1.35 + np.cumsum(rng.normal(0, 0.005, len(d))),
        "UK10Y": 3 + np.cumsum(rng.normal(0, 0.04, len(d))) * 0.3,
        "DE10Y": 2 + np.cumsum(rng.normal(0, 0.04, len(d))) * 0.3,
        "JP10Y": 0.5 + np.cumsum(rng.normal(0, 0.02, len(d))) * 0.3,
        "JP30Y": 1.5 + np.cumsum(rng.normal(0, 0.02, len(d))) * 0.3,
        "US_BE10": 2.2 + np.cumsum(rng.normal(0, 0.01, len(d))) * 0.3,
    }, index=d)
    years = range(1990, 2032)
    iso_all = sorted({C.ISO3[c] for c in C.COUNTRIES})
    debt0 = {"USA": 60, "DEU": 40, "FRA": 40, "ITA": 95, "JPN": 70, "GBR": 30}
    imf_data = {}
    debt = pd.DataFrame({i: np.linspace(debt0.get(i, rng.uniform(20, 70)),
                                        debt0.get(i, 50) * 2.1, len(years)) + rng.normal(0, 2, len(years))
                         for i in iso_all}, index=years)
    prim = -0.02 * debt + 1.5 + rng.normal(0, 1.5, debt.shape)
    prim = pd.DataFrame(prim, index=years, columns=iso_all)
    imf_data["debt"] = debt
    imf_data["primary"] = prim
    imf_data["overall"] = prim - debt * 0.025
    imf_data["revenue"] = pd.DataFrame(rng.normal(40, 5, debt.shape), index=years, columns=iso_all)
    imf_data["structural"] = imf_data["primary"] - 1.0
    imf_data["real_g"] = pd.DataFrame(rng.normal(1.5, 1.2, debt.shape), index=years, columns=iso_all)
    imf_data["infl"] = pd.DataFrame(rng.normal(2.2, 0.8, debt.shape), index=years, columns=iso_all)
    move = pd.Series(90 + np.cumsum(rng.normal(0, 1, len(d))) * 0.2, index=d)
    HEALTH.append(("MOCK DATA", "synthetic test data — not real", str(d[-1])[:10]))
    return {"y10": y10, "s3m": s3m, "daily": daily, "imf": imf_data, "move": move}

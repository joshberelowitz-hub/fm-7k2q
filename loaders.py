"""
loaders.py — pulls public data. Every source is cached to data/*.csv; if a download
fails, the last cached copy is used and the failure is shown on the page.
"""
from __future__ import annotations

import io
import os

import numpy as np
import pandas as pd
import requests

import config as C

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0 (fiscal-monitor; public data research)"}
TIMEOUT = (10, 30)  # connect, read seconds
HEALTH: list[tuple[str, str, str]] = []


def _cached(name: str, fetch, dated: bool = True) -> pd.DataFrame | None:
    import time
    path = os.path.join(CACHE, f"{name}.csv")
    t0 = time.time()
    try:
        df = fetch()
        print(f"  ok   {name} ({time.time() - t0:.1f}s)", flush=True)
        if df is None or len(df) == 0:
            raise ValueError("empty response")
        os.makedirs(CACHE, exist_ok=True)
        df.to_csv(path)
        last = str(df.index.max())[:10] if dated else ""
        HEALTH.append((name, "fresh", last))
        return df
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {name} ({time.time() - t0:.1f}s): {type(e).__name__}: {str(e)[:120]}", flush=True)
        if os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=dated)
            last = str(df.index.max())[:10] if dated else ""
            HEALTH.append((name, f"cached copy (download failed: {type(e).__name__})", last))
            return df
        HEALTH.append((name, f"FAILED: {type(e).__name__}: {str(e)[:80]}", ""))
        return None


# ---------------------------------------------------------------- FRED
def _fred(series_id: str) -> pd.DataFrame:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", series_id]
    df["date"] = pd.to_datetime(df["date"])
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    return df.set_index("date").dropna()


def fred(series_id: str) -> pd.Series | None:
    df = _cached(f"fred_{series_id}", lambda: _fred(series_id))
    return None if df is None else df.iloc[:, 0]


# ---------------------------------------------------------------- IMF
def _imf(indicator: str, iso3s: list[str]) -> pd.DataFrame:
    url = ("https://www.imf.org/external/datamapper/api/v1/" + indicator + "/" + "/".join(iso3s))
    r = requests.get(url, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    vals = r.json().get("values", {}).get(indicator, {})
    rows = [(c, int(y), v) for c, d in vals.items() for y, v in d.items() if v is not None]
    df = pd.DataFrame(rows, columns=["iso3", "year", "value"])
    return df


def imf(key: str, iso3s: list[str]) -> pd.DataFrame | None:
    """Returns a year x iso3 table (values as published, % units)."""
    ind = C.IMF_INDICATORS[key]
    df = _cached(f"imf_{ind}", lambda: _imf(ind, iso3s), dated=False)
    if df is None:
        return None
    return df.pivot_table(index="year", columns="iso3", values="value")


# ---------------------------------------------------------------- Yahoo
def _yahoo(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(ticker, period="max", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Close"]].rename(columns={"Close": ticker}).dropna()


def yahoo(ticker: str) -> pd.Series | None:
    df = _cached(f"yahoo_{ticker.replace('^', '')}", lambda: _yahoo(ticker))
    return None if df is None else df.iloc[:, 0]


# ---------------------------------------------------------------- all
def load_all() -> dict:
    from concurrent.futures import ThreadPoolExecutor
    allc = C.COUNTRIES + C.FACTOR_EXTRA
    fred_ids = ([C.fred_10y(c) for c in allc] + [C.fred_3m(c) for c in allc]
                + list(C.FRED_DAILY.values()))
    iso_all = sorted(set(C.PANEL_ISO3) | {C.ISO3[c] for c in C.COUNTRIES})
    with ThreadPoolExecutor(max_workers=8) as ex:
        fred_res = dict(zip(fred_ids, ex.map(fred, fred_ids)))
        imf_keys = list(C.IMF_INDICATORS)
        imf_res = dict(zip(imf_keys, ex.map(lambda k: imf(k, iso_all), imf_keys)))
    move = yahoo("^MOVE")
    y10 = pd.DataFrame({c: fred_res[C.fred_10y(c)] for c in allc if fred_res[C.fred_10y(c)] is not None})
    s3m = pd.DataFrame({c: fred_res[C.fred_3m(c)] for c in allc if fred_res[C.fred_3m(c)] is not None})
    daily = pd.DataFrame({k: fred_res[sid] for k, sid in C.FRED_DAILY.items() if fred_res[sid] is not None})
    return {"y10": y10, "s3m": s3m, "daily": daily, "imf": imf_res, "move": move}


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
        "US_TP_KW": 0.5 + np.cumsum(rng.normal(0, 0.02, len(d))) * 0.3,
        "USD_BROAD": 110 + np.cumsum(rng.normal(0, 0.3, len(d))),
        "JPY_PER_USD": 120 + np.cumsum(rng.normal(0, 0.5, len(d))),
        "USD_PER_EUR": 1.15 + np.cumsum(rng.normal(0, 0.004, len(d))),
        "USD_PER_GBP": 1.35 + np.cumsum(rng.normal(0, 0.005, len(d))),
        "US_CORE_CPI": 200 * np.exp(np.cumsum(np.full(len(d), 0.025 / 260))),
    }, index=d)
    years = range(1990, 2032)
    iso_all = sorted(set(C.PANEL_ISO3) | {C.ISO3[c] for c in C.COUNTRIES})
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
    imf_data["real_g"] = pd.DataFrame(rng.normal(1.5, 1.2, debt.shape), index=years, columns=iso_all)
    imf_data["infl"] = pd.DataFrame(rng.normal(2.2, 0.8, debt.shape), index=years, columns=iso_all)
    imf_data["output_gap"] = pd.DataFrame(rng.normal(0, 1.5, debt.shape), index=years, columns=iso_all)
    move = pd.Series(90 + np.cumsum(rng.normal(0, 1, len(d))) * 0.2, index=d)
    HEALTH.append(("MOCK DATA", "synthetic test data — not real", str(d[-1])[:10]))
    return {"y10": y10, "s3m": s3m, "daily": daily, "imf": imf_data, "move": move}

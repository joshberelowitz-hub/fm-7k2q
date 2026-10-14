"""
tp_model.py — builds zero curves and runs the ACM term premium model per country,
following the Bloomberg Economics implementation (K=5 factors, 3m–30y, observed-yield TP).

Estimation samples follow Bloomberg: US from Jun-1961, Germany from Jan-1998, UK from Jan-1996.
Japan: sample from Jan-1992. Estimates starting 1990–1995 give 220–234bp for Aug-2026 and track
Bloomberg Intelligence's published series (BIFITPJP, 238bp); a sample starting after 1999 is dominated by
the zero bound and wrongly attributes the recent rise in yields to expected short rates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

from acm import ACM, svensson, to_monthly_grid

SAMPLES = {"US": "1961-06", "DE": "1998-01", "UK": "1996-01", "JP": "1992-01"}
GRID = np.arange(1, 361)


def _me(idx) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(idx)) + pd.offsets.MonthEnd(0)


def _intcols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [int(float(c)) for c in df.columns]
    return df[sorted(df.columns)]


# ------------------------------------------------------------------ country curves
def us_curves(gsw: pd.DataFrame):
    p = gsw[["BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2"]].astype(float).dropna()
    m = p.resample("ME").last().dropna()
    monthly = pd.DataFrame([svensson(GRID / 12, *r) for r in m.values], index=m.index, columns=GRID)
    d = p.iloc[-5:]
    daily = pd.DataFrame([svensson(GRID / 12, *r) for r in d.values], index=d.index, columns=GRID)
    return monthly, daily


def de_curves(de_m, de_d, euribor, oecd3m):
    nodes = _intcols(de_m)
    nodes.index = _me(nodes.index)
    e = euribor.iloc[:, 0].copy()
    e.index = _me(e.index)
    s3 = oecd3m.copy()
    s3.index = _me(s3.index)
    nodes.insert(0, 1, e.reindex(nodes.index))
    nodes.insert(1, 3, s3.reindex(nodes.index).where(nodes[1].isna()))
    monthly = to_monthly_grid(nodes)
    daily = None
    if de_d is not None and len(de_d):
        dn = _intcols(de_d).dropna(how="all").iloc[-5:]
        dn.insert(0, 1, float(e.dropna().iloc[-1]))
        daily = to_monthly_grid(dn)
    return monthly, daily


def uk_curves(uk_m, uk_d):
    nodes = _intcols(uk_m)
    nodes.index = _me(nodes.index)
    nodes = nodes[~nodes.index.duplicated(keep="last")]
    monthly = to_monthly_grid(nodes)
    daily = None
    if uk_d is not None and len(uk_d):
        daily = to_monthly_grid(_intcols(uk_d).dropna(how="all").iloc[-5:])
    return monthly, daily


def _par_to_zero(row: pd.Series) -> pd.Series | None:
    T = np.array([float(str(c).rstrip("Y")) for c in row.index])
    p = row.values.astype(float)
    ok = ~np.isnan(p)
    if ok.sum() < 5:
        return None
    f = PchipInterpolator(T[ok], p[ok], extrapolate=False)
    grid = np.arange(0.5, T[ok].max() + 0.01, 0.5)
    par = f(grid)
    par[grid < T[ok].min()] = p[ok][0]
    D = np.zeros(len(grid))
    for i, c in enumerate(par / 100):
        D[i] = (1 - c / 2 * D[:i].sum()) / (1 + c / 2)
    return pd.Series(-np.log(D) / grid * 100, index=(grid * 12).round().astype(int))


def jp_curves(mof, oecd3m):
    cols = [c for c in mof.columns if str(c).endswith("Y")]
    m = mof[cols].astype(float).resample("ME").last()
    z = {d: _par_to_zero(r) for d, r in m.iterrows()}
    nodes = pd.DataFrame({d: v for d, v in z.items() if v is not None}).T
    s3 = oecd3m.copy()
    s3.index = _me(s3.index)
    nodes.insert(0, 3, s3.reindex(nodes.index))
    nodes = nodes[sorted(nodes.columns)]
    monthly = to_monthly_grid(nodes)
    dz = {d: _par_to_zero(r) for d, r in mof[cols].astype(float).iloc[-5:].iterrows()}
    dn = pd.DataFrame({d: v for d, v in dz.items() if v is not None}).T
    dn.insert(0, 3, float(s3.dropna().iloc[-1]))
    daily = to_monthly_grid(dn[sorted(dn.columns)])
    return monthly, daily


# ------------------------------------------------------------------ run
def run_all(curves: dict, oecd_rates: pd.DataFrame | None) -> dict:
    """Returns {'monthly': DataFrame (cols like US_tp120), 'latest': DataFrame, 'models': {...},
    'jp_range': DataFrame, 'notes': list}."""
    o3 = (lambda iso: oecd_rates[f"IR3TIB_{iso}"]) if oecd_rates is not None else (lambda iso: pd.Series(dtype=float))
    builders = {
        "US": lambda: us_curves(curves["gsw"]),
        "DE": lambda: de_curves(curves["de_m"], curves["de_d"], curves["euribor"], o3("DEU")),
        "UK": lambda: uk_curves(curves["uk_m"], curves["uk_d"]),
        "JP": lambda: jp_curves(curves["jp"], o3("JPN")),
    }
    monthly, latest, models, notes = {}, {}, {}, []
    jp_range = {}
    for c, build in builders.items():
        try:
            Ym, Yd = build()
            Y = Ym.loc[SAMPLES[c]:].dropna()
            mod = ACM(k=5).fit(Y)
            dm = mod.decompose(Y)
            models[c] = mod
            for col in ("y120", "rf120", "tp120", "y360", "rf360", "tp360"):
                monthly[f"{c}_{col}"] = dm[col]
            src = Yd if Yd is not None else Y.iloc[[-1]]
            dd = mod.decompose(src.dropna()).iloc[-1]
            latest[c] = {"date": src.dropna().index[-1], "y10": dd["y120"], "rf10": dd["rf120"],
                         "tp10": dd["tp120"], "y30": dd["y360"], "rf30": dd["rf360"], "tp30": dd["tp360"],
                         "fit_err_bp": float((dm["y120"] - dm["fit120"]).abs().mean() * 100),
                         "sample_start": SAMPLES[c]}
        except Exception as e:  # noqa: BLE001
            notes.append(f"{c}: {type(e).__name__}: {e}")
    return {"monthly": pd.DataFrame(monthly), "latest": pd.DataFrame(latest).T,
            "models": models, "jp_range": pd.DataFrame(jp_range).T, "notes": notes}

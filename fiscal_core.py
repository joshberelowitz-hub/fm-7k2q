"""
fiscal_core.py — analytics for the fiscal sustainability monitor.

Pure functions only: no data loading. Feed them pandas objects built by the
loaders (IMF, Bloomberg). All rates/ratios are in DECIMALS (0.03 = 3%, 1.10 = 110% of GDP)
unless a name says _bp or _pp.

Sections
  1. Debt dynamics (r-g, debt-stabilising primary balance, projections)
  2. Fiscal fatigue (reaction function, debt limit, fiscal space)
  3. Cyclical scenarios (recession shock, country-specific r response)
  4. Term premium decomposition (global factor, idiosyncratic residual, global drivers)
  5. "How much is priced" (implied stress probability, implied debt path, market-rate required PB)
  6. Heatmap scoring
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Debt dynamics
# ---------------------------------------------------------------------------
def effective_rate(interest_pct_gdp: pd.Series, debt_pct_gdp: pd.Series,
                   nominal_g: pd.Series) -> pd.Series:
    """Effective interest rate = interest paid_t / debt_{t-1}.
    Inputs are % of GDP, so rescale lagged debt to this year's GDP: debt_{t-1}/(1+g_t)."""
    return interest_pct_gdp / (debt_pct_gdp.shift(1) / (1 + nominal_g))


def stabilising_pb(debt: float | np.ndarray, r, g):
    """Primary balance (% GDP) that holds debt/GDP constant: d*(r-g)/(1+g)."""
    return debt * (r - g) / (1 + g)


def project_debt(d0: float, r, g, pb, years: int | None = None) -> np.ndarray:
    """d_{t+1} = d_t*(1+r_t)/(1+g_t) - pb_t. r, g, pb may be scalars or arrays."""
    arrays = [np.atleast_1d(x) for x in (r, g, pb)]
    n = years or max(len(a) for a in arrays)
    r, g, pb = (np.resize(a, n) for a in arrays)
    path = np.empty(n + 1)
    path[0] = d0
    for t in range(n):
        path[t + 1] = path[t] * (1 + r[t]) / (1 + g[t]) - pb[t]
    return path


def required_adjustment(debt: float, r: float, g: float, current_capb: float) -> dict:
    """Gap between debt-stabilising PB and the cyclically adjusted PB (positive = tightening needed)."""
    req = stabilising_pb(debt, r, g)
    return {"r_minus_g": r - g, "required_pb": req,
            "current_capb": current_capb, "adjustment_needed": req - current_capb}


# ---------------------------------------------------------------------------
# 2. Fiscal fatigue (Ghosh, Kim, Mendoza, Ostry & Qureshi 2013)
# ---------------------------------------------------------------------------
def fit_reaction_function(pb: pd.Series, lagged_debt: pd.Series,
                          controls: pd.DataFrame | None = None) -> dict:
    """OLS: pb_t = a + b1 d + b2 d^2 + b3 d^3 + controls (e.g. output gap).
    Use a cross-country panel (pooled) for stable coefficients; GKMOQ add fixed effects."""
    X = pd.DataFrame({"const": 1.0, "d": lagged_debt, "d2": lagged_debt ** 2, "d3": lagged_debt ** 3})
    if controls is not None:
        X = X.join(controls)
    df = X.join(pb.rename("pb")).dropna()
    beta, *_ = np.linalg.lstsq(df.drop(columns="pb").values, df["pb"].values, rcond=None)
    return dict(zip(df.drop(columns="pb").columns, beta))


def debt_limit(coefs: dict, r: float, g: float, intercept_adj: float = 0.0,
               grid=np.linspace(0.3, 3.0, 2701)) -> float:
    """Debt limit = highest debt level where the reaction-function PB still covers
    the interest-growth burden. Returns NaN if the curves never cross from above
    (no sustainable limit in the range). intercept_adj: country fixed effect / control values."""
    pb_rf = (coefs["const"] + intercept_adj + coefs["d"] * grid
             + coefs["d2"] * grid ** 2 + coefs["d3"] * grid ** 3)
    burden = stabilising_pb(grid, r, g)
    diff = pb_rf - burden
    crossings = np.where((diff[:-1] >= 0) & (diff[1:] < 0))[0]
    return float(grid[crossings[-1]]) if len(crossings) else float("nan")


def fiscal_space(current_debt: float, limit: float) -> float:
    return limit - current_debt


# ---------------------------------------------------------------------------
# 3. Cyclical scenarios
# ---------------------------------------------------------------------------
def recession_scenario(d0: float, r: float, g: float, capb: float, years: int = 5,
                       output_gap_shock=(-0.02, -0.03, -0.015, -0.005, 0.0),
                       semi_elasticity: float = 0.5,
                       r_beta_to_gap_bp: float = 0.0) -> pd.DataFrame:
    """Compare baseline vs recession debt paths.
    - Deficit widens by semi_elasticity * output gap (automatic stabilisers only).
    - Nominal g falls by the change in the output gap each year.
    - r responds by r_beta_to_gap_bp per 1pp of output gap: NEGATIVE for safe havens
      (r falls in recession), POSITIVE for spread countries. E.g. +30 = r rises 30bp per 1pp gap."""
    gap = np.resize(np.array(output_gap_shock), years)
    dgap = np.diff(np.concatenate([[0.0], gap]))
    base = project_debt(d0, r, g, capb, years)
    pb_rec = capb + semi_elasticity * gap
    g_rec = g + dgap
    r_rec = r - r_beta_to_gap_bp * (gap * 100) / 10_000
    rec = project_debt(d0, r_rec, g_rec, pb_rec, years)
    return pd.DataFrame({"baseline": base, "recession": rec, "difference": rec - base})


# ---------------------------------------------------------------------------
# 4. Term premium decomposition
# ---------------------------------------------------------------------------
def _ols(y: pd.Series, X: pd.DataFrame):
    df = X.join(y.rename("_y"), how="inner").dropna()
    Xv = np.column_stack([np.ones(len(df)), df.drop(columns="_y").values])
    beta, *_ = np.linalg.lstsq(Xv, df["_y"].values, rcond=None)
    fitted = Xv @ beta
    resid = pd.Series(df["_y"].values - fitted, index=df.index)
    coefs = pd.Series(beta, index=["const"] + list(df.drop(columns="_y").columns))
    return coefs, resid


def global_factor(tp: pd.DataFrame, exclude: str | None = None) -> pd.Series:
    """First principal component of term premia (columns = countries), scaled back to bp
    so it reads like an average term premium. Pass exclude=country for a leave-one-out factor."""
    panel = tp.drop(columns=[exclude]) if exclude else tp
    panel = panel.dropna()
    z = (panel - panel.mean()) / panel.std()
    _, _, vt = np.linalg.svd(z.values, full_matrices=False)
    w = vt[0] * np.sign(vt[0].sum())          # sign so the factor rises with term premia
    w = w / w.sum()
    pc = pd.Series(z.values @ w, index=panel.index)
    # rescale to bp units of the cross-sectional average
    avg = panel.mean(axis=1)
    return pc * avg.std() / pc.std() + avg.mean()


def idiosyncratic_premium(tp: pd.DataFrame, window: int | None = None,
                          factor_universe: list[str] | None = None) -> pd.DataFrame:
    """For each country: regress its term premium on the leave-one-out global factor;
    residual = idiosyncratic premium. window=None -> full-sample beta; else rolling beta (obs).
    factor_universe: countries used to BUILD the factor. A big shock in one country leaks
    into everyone else's factor, so consider building it from a broader, calmer set
    (e.g. add AU, CA, SE, CH) rather than only the countries you are diagnosing."""
    universe = factor_universe or list(tp.columns)
    out = {}
    for c in tp.columns:
        f = global_factor(tp[[u for u in universe if u != c]]).rename("global")
        if window is None:
            _, resid = _ols(tp[c], f.to_frame())
            out[c] = resid
        else:
            y, x = tp[c].align(f, join="inner")
            cov = y.rolling(window).cov(x)
            beta = cov / x.rolling(window).var()
            alpha = y.rolling(window).mean() - beta * x.rolling(window).mean()
            out[c] = y - (alpha + beta * x)
    return pd.DataFrame(out)


def betas_to_global(tp: pd.DataFrame) -> pd.Series:
    return pd.Series({c: _ols(tp[c], global_factor(tp, exclude=c).rename("g").to_frame())[0]["g"]
                      for c in tp.columns})


def decompose_global(global_tp: pd.Series, drivers: pd.DataFrame, start, end,
                     fiscal_cols=("dm_debt",)) -> pd.Series:
    """Regress global TP on drivers (e.g. inflation uncertainty, MOVE, CB holdings share,
    aggregate DM debt or deficit). Attribute the start->end change to each driver:
    coef * change in driver. 'fiscal' = sum over fiscal_cols; 'unexplained' = residual change."""
    coefs, resid = _ols(global_tp, drivers)
    d = drivers.loc[end] - drivers.loc[start]
    contrib = coefs.drop("const") * d
    total = global_tp.loc[end] - global_tp.loc[start]
    out = contrib.copy()
    out["fiscal_total"] = contrib[[c for c in fiscal_cols if c in contrib]].sum()
    out["unexplained"] = total - contrib.sum()
    out["total_change"] = total
    return out


# ---------------------------------------------------------------------------
# 5. How much is priced
# ---------------------------------------------------------------------------
def implied_stress_probability(current, benign, stressed):
    """Linear weight between a benign and a stressed state: (x - benign)/(stressed - benign),
    clipped to [0, 1]. Use on idiosyncratic premia or relative spreads, not raw levels."""
    p = (np.asarray(current, dtype=float) - benign) / (stressed - benign)
    return np.clip(p, 0.0, 1.0)


def implied_debt_path(fiscal_premium_bp: float, bp_per_pp_debt: float = 3.5,
                      baseline_debt_pct: float | None = None) -> dict:
    """Back out the extra debt/GDP the market is pricing: premium / elasticity.
    Default elasticity ~3-4bp per pp of projected debt (Laubach 2009). Sensitivity-test it."""
    extra_pp = fiscal_premium_bp / bp_per_pp_debt
    out = {"implied_extra_debt_pp": extra_pp}
    if baseline_debt_pct is not None:
        out["implied_debt_pct"] = baseline_debt_pct + extra_pp
    return out


def market_rate_required_pb(debt: float, forward_r: float, g: float,
                            max_historical_pb: float, feasible_pb: float | None = None) -> dict:
    """PB needed to stabilise debt if the effective rate converges to the market forward rate,
    compared with what has historically been achieved / judged politically feasible."""
    req = stabilising_pb(debt, forward_r, g)
    out = {"required_pb_at_market_r": req, "max_historical_pb": max_historical_pb,
           "gap_vs_history": req - max_historical_pb}
    if feasible_pb is not None:
        out["gap_vs_feasible"] = req - feasible_pb
    return out


# ---------------------------------------------------------------------------
# 6. Heatmap scoring
# ---------------------------------------------------------------------------
def heatmap(table: pd.DataFrame, higher_is_worse: dict[str, bool] | None = None) -> pd.DataFrame:
    """Rank-based 1-5 scores per column (5 = most stressed). table: rows = countries,
    columns = metrics. higher_is_worse maps column -> bool (default True). NaNs stay NaN
    and are ignored in the composite."""
    higher_is_worse = higher_is_worse or {}
    scores = pd.DataFrame(index=table.index)
    for c in table.columns:
        s = table[c] if higher_is_worse.get(c, True) else -table[c]
        pct = s.rank(pct=True)
        scores[c] = np.ceil(pct * 5).clip(1, 5)
    scores["composite"] = scores.mean(axis=1, skipna=True).round(1)
    return scores

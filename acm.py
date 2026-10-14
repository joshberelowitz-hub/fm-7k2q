"""
acm.py — Adrian, Crump & Moench (2013) term premium model, following the Bloomberg
Economics implementation (Galvão & Sakthivel, 2026):
  - zero-coupon yields 3m–30y, monthly grid; factors = first K principal components
  - VAR(1) on factors; three-step ACM regressions on end-of-month data
  - risk-free yield = model yield with zero market prices of risk
  - term premium = OBSERVED yield minus risk-free yield
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def svensson(n_years, b0, b1, b2, b3, t1, t2):
    """Svensson zero yield (same units as betas). n_years > 0, array-like."""
    n = np.asarray(n_years, dtype=float)
    x1, x2 = n / t1, n / t2
    f1 = (1 - np.exp(-x1)) / x1
    f2 = f1 - np.exp(-x1)
    f3 = (1 - np.exp(-x2)) / x2 - np.exp(-x2)
    return b0 + b1 * f1 + b2 * f2 + b3 * f3


def to_monthly_grid(nodes: pd.DataFrame, max_n: int = 360) -> pd.DataFrame:
    """nodes: index = dates, columns = maturities in MONTHS (ints), values = zero yields (%).
    Returns a full 1..max_n monthly grid via monotone cubic (PCHIP) interpolation;
    flat extrapolation beyond the last node."""
    from scipy.interpolate import PchipInterpolator
    grid = np.arange(1, max_n + 1)
    out = np.full((len(nodes), max_n), np.nan)
    cols = np.array(nodes.columns, dtype=float)
    for i, row in enumerate(nodes.values):
        ok = ~np.isnan(row)
        if ok.sum() < 4:
            continue
        x, y = cols[ok], row[ok]
        f = PchipInterpolator(x, y, extrapolate=False)
        v = f(grid)
        v[grid > x.max()] = y[-1]
        v[grid < x.min()] = y[0]
        out[i] = v
    return pd.DataFrame(out, index=nodes.index, columns=grid)


class ACM:
    def __init__(self, k: int = 5, pc_maturities=None, rx_maturities=None, max_n: int = 360):
        self.k = k
        self.max_n = max_n
        self.pc_mat = pc_maturities or [3, 6] + list(range(12, max_n + 1, 12))
        self.rx_mat = rx_maturities or list(range(6, max_n + 1, 6))

    def fit(self, yields: pd.DataFrame) -> "ACM":
        """yields: monthly (end-of-month) zero yields in %, columns 1..max_n months."""
        Y = yields.dropna()
        self.dates = Y.index
        ylog = Y.values / 100.0                       # annual, decimal, cont. comp.
        n = np.array(Y.columns, dtype=float)
        logP = -ylog * n / 12.0                        # log prices
        # --- factors: PCs of yields at pc maturities
        pcY = Y[self.pc_mat].values / 100.0
        self.pc_mean = pcY.mean(0)
        u, s, vt = np.linalg.svd(pcY - self.pc_mean, full_matrices=False)
        self.W = vt[: self.k].T                        # loadings (n_pc x k)
        X = (pcY - self.pc_mean) @ self.W              # T x k
        T = len(X)
        # --- step 1: VAR(1) with intercept
        Z = np.column_stack([np.ones(T - 1), X[:-1]])
        coef, *_ = np.linalg.lstsq(Z, X[1:], rcond=None)
        self.mu, self.Phi = coef[0], coef[1:].T
        V = X[1:] - Z @ coef                           # (T-1) x k
        self.Sigma = V.T @ V / (T - 1)
        # --- step 2: excess returns regressions
        col = {m: i for i, m in enumerate(Y.columns)}
        r = ylog[:, col[1]] / 12.0                     # one-month rate
        rx = np.column_stack([logP[1:, col[m - 1]] - logP[:-1, col[m]] - r[:-1] for m in self.rx_mat])
        Zr = np.column_stack([np.ones(T - 1), V, X[:-1]])
        b, *_ = np.linalg.lstsq(Zr, rx, rcond=None)    # (1+2k) x N
        a, beta, c = b[0], b[1:1 + self.k], b[1 + self.k:].T   # beta: k x N ; c: N x k
        E = rx - Zr @ b
        sigma2 = (E ** 2).sum() / E.size
        # --- step 3: prices of risk
        Bstar = np.stack([np.outer(beta[:, i], beta[:, i]).ravel() for i in range(beta.shape[1])])
        ainv = np.linalg.solve(beta @ beta.T, beta)    # k x N  = (ββ')^-1 β
        self.lambda0 = ainv @ (a + 0.5 * (Bstar @ self.Sigma.ravel() + sigma2))
        self.lambda1 = ainv @ c
        self.sigma2 = sigma2
        # --- short rate equation
        Zs = np.column_stack([np.ones(T), X])
        d, *_ = np.linalg.lstsq(Zs, r, rcond=None)
        self.delta0, self.delta1 = d[0], d[1:]
        self.A, self.B = self._recursion(self.lambda0, self.lambda1)
        self.Arf, self.Brf = self._recursion(np.zeros(self.k), np.zeros((self.k, self.k)))
        self.X = pd.DataFrame(X, index=Y.index)
        return self

    def _recursion(self, l0, l1):
        A = np.zeros(self.max_n + 1)
        B = np.zeros((self.max_n + 1, self.k))
        for n in range(self.max_n):
            Bn = B[n]
            A[n + 1] = A[n] + Bn @ (self.mu - l0) + 0.5 * (Bn @ self.Sigma @ Bn + self.sigma2) - self.delta0
            B[n + 1] = Bn @ (self.Phi - l1) - self.delta1
        return A, B

    def factors(self, yields: pd.DataFrame) -> pd.DataFrame:
        """Project any (e.g. daily) yields onto the estimated PC loadings."""
        Y = yields[self.pc_mat].dropna() / 100.0
        return pd.DataFrame((Y.values - self.pc_mean) @ self.W, index=Y.index)

    def decompose(self, yields: pd.DataFrame, maturities=(24, 60, 120, 360)) -> pd.DataFrame:
        """Returns observed yield, model-fitted yield, risk-free yield and term premium (all %)."""
        X = self.factors(yields)
        out = {}
        for n in maturities:
            obs = yields.loc[X.index, n]
            fit = -(self.A[n] + X.values @ self.B[n]) / n * 12 * 100
            rf = -(self.Arf[n] + X.values @ self.Brf[n]) / n * 12 * 100
            out[f"y{n}"] = obs
            out[f"fit{n}"] = pd.Series(fit, index=X.index)
            out[f"rf{n}"] = pd.Series(rf, index=X.index)
            out[f"tp{n}"] = obs - pd.Series(rf, index=X.index)
        return pd.DataFrame(out)

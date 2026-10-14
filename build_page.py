"""
build_page.py — loads data, runs the analytics in fiscal_core.py, writes site/index.html.

    python build_page.py          # real public data
    python build_page.py --mock   # synthetic data, for testing the page
"""
from __future__ import annotations

import datetime as dt
import html
import os
import sys
import traceback

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import config as C
import fiscal_core as F
import loaders as L
import tp_model as TM

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
COLORS = {"US": "#1f4e79", "DE": "#444444", "FR": "#2e75b6", "IT": "#2e8b57",
          "JP": "#c0392b", "UK": "#8e44ad"}
SECTIONS: list[str] = []
WARNINGS: list[str] = []
_first_fig = True


# ----------------------------------------------------------------- html helpers
def fig_html(fig: go.Figure, height: int = 380) -> str:
    global _first_fig
    fig.update_traces(mode="lines", selector=dict(type="scatter"))
    fig.update_layout(height=height, margin=dict(l=40, r=20, t=40, b=40),
                      template="plotly_white", legend=dict(orientation="h", y=-0.15),
                      font=dict(family="Arial, sans-serif", size=12))
    out = fig.to_html(full_html=False, include_plotlyjs=True if _first_fig else False,
                      config={"displaylogo": False, "responsive": True})
    _first_fig = False
    return f'<div class="fig">{out}</div>'


def table_html(df: pd.DataFrame, fmt: dict | None = None) -> str:
    fmt = fmt or {}
    d = df.copy()
    for c in d.columns:
        f = fmt.get(c)
        if f:
            d[c] = d[c].map(lambda v, f=f: "" if pd.isna(v) else f.format(v))
    return '<div class="tbl">' + d.to_html(escape=True, na_rep="", border=0) + "</div>"


SHADE = {0: "#e8f5e9", 1: "#fff3cd", 2: "#f8d7da"}


def styled_table(df: pd.DataFrame, fmt: dict | None = None, rules: dict | None = None) -> str:
    """Table with per-cell background colours. rules: column -> function(value) -> 0/1/2 (green/amber/red)
    or None for no colour."""
    fmt, rules = fmt or {}, rules or {}
    hdr = "<th></th>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = ""
    for idx, r in df.iterrows():
        cells = ""
        for c in df.columns:
            v = r[c]
            txt = "" if (not isinstance(v, str) and pd.isna(v)) else (fmt[c].format(v) if c in fmt else str(v))
            lv = None
            if c in rules and not (not isinstance(v, str) and pd.isna(v)):
                lv = rules[c](v)
            style = f' style="background:{SHADE[lv]}"' if lv is not None else ""
            align = "" if not isinstance(v, str) else ' class="txt"'
            cells += f"<td{style}{align}>{html.escape(txt)}</td>"
        rows += f"<tr><th>{html.escape(str(idx))}</th>{cells}</tr>"
    return f'<div class="tbl"><table><tr>{hdr}</tr>{rows}</table></div>'


def section(title: str, body: str, note: str = "", details: str = "") -> None:
    n = f'<p class="explain">{note}</p>' if note else ""
    d = f'<p class="note details">{details}</p>' if details else ""
    SECTIONS.append(f"<section><h2>{html.escape(title)}</h2>{n}{body}{d}</section>")


def safe(title: str):
    """Decorator: if a section fails, show the error instead of breaking the page."""
    def wrap(fn):
        def inner(*a, **k):
            try:
                return fn(*a, **k)
            except Exception:  # noqa: BLE001
                tb = traceback.format_exc()
                WARNINGS.append(f"{title}: {tb.splitlines()[-1]}")
                section(title, f"<pre class='err'>{html.escape(tb[-1500:])}</pre>",
                        "This section failed on the last run. Paste this error to Claude to fix.")
                return None
        return inner
    return wrap


# ----------------------------------------------------------------- analytics
def fiscal_table(data: dict, base_year: int) -> pd.DataFrame:
    imf = data["imf"]
    rows = {}
    for c in C.COUNTRIES:
        i = C.ISO3[c]
        debt = imf["debt"][i] / 100
        prim = imf["primary"][i] / 100
        overall = imf["overall"][i] / 100
        g_nom = (1 + imf["real_g"][i] / 100) * (1 + imf["infl"][i] / 100) - 1
        interest = prim - overall
        eff_r = F.effective_rate(interest, debt, g_nom)
        y = base_year
        g_fwd = C.LTCMA_G.get(c, g_nom.loc[y + 1:y + 5].mean())
        r_mkt = C.LTCMA_R.get(c, latest_10y(data, c) / 100)
        hist_pb = prim.loc[:y - 1].rolling(5).mean()
        d0, pb0, r0 = debt.get(y), prim.get(y), eff_r.get(y)
        rows[c] = {
            "debt": d0, "primary_bal": pb0, "eff_r": r0, "mkt_r_10y": r_mkt, "fwd_g": g_fwd,
            "r_g_eff": r0 - g_fwd, "r_g_mkt": r_mkt - g_fwd,
            "req_pb_eff": F.stabilising_pb(d0, r0, g_fwd),
            "req_pb_mkt": F.stabilising_pb(d0, r_mkt, g_fwd),
            "best_5y_pb": hist_pb.max(),
        }
    t = pd.DataFrame(rows).T.astype(float)
    t["adj_gap_mkt"] = t["req_pb_mkt"] - t["primary_bal"]
    t["gap_vs_best"] = t["req_pb_mkt"] - t["best_5y_pb"]
    return t


def latest_10y(data: dict, c: str) -> float:
    col = f"{c}10Y"
    if col in data["daily"] and data["daily"][col].notna().any():
        return float(data["daily"][col].dropna().iloc[-1])
    return float(data["y10"][c].dropna().iloc[-1])


def tp_proxies(data: dict) -> pd.DataFrame:
    """Crude term premium: 10y yield minus expected average 3m rate over 10y from an AR(1).
    In bp. Validated against Kim-Wright for the US on the page."""
    out = {}
    n = 120
    for c in data["y10"].columns:
        if c not in data["s3m"]:
            continue
        s = data["s3m"][c].loc["1999":].dropna()
        if len(s) < 60:
            continue
        x, y = s.values[:-1], s.values[1:]
        b, a = np.polyfit(x, y, 1)
        b = min(b, 0.995)
        mu = a / (1 - b)
        w = b * (1 - b ** n) / (n * (1 - b))
        exp_avg = mu + (s - mu) * w
        out[c] = (data["y10"][c] - exp_avg) * 100
    return pd.DataFrame(out).dropna(how="all")


# ----------------------------------------------------------------- sections
@safe("Data health")
def s_health():
    df = pd.DataFrame(L.HEALTH, columns=["source", "status", "latest obs"]).set_index("source")
    bad = df[~df["status"].str.startswith("fresh")]
    body = (f"<p>{len(df) - len(bad)} of {len(df)} sources refreshed on this run.</p>"
            + (table_html(bad) if len(bad) else ""))
    body += "<details><summary>All sources</summary>" + table_html(df) + "</details>"
    section("Data health", body)


def willingness(data, ftab, base_year) -> pd.DataFrame:
    """Data-based willingness from IMF structural primary balance (structural balance + net interest):
    revealed = change over the past 3 years, stated = IMF-projected change over the next 5 (announced
    policies), coverage = stated change / adjustment needed at market rates."""
    imf = data["imf"]
    rows = {}
    for c in C.COUNTRIES:
        i = C.ISO3[c]
        sp = imf["structural"][i] + (imf["primary"][i] - imf["overall"][i])
        rev = sp.get(base_year) - sp.get(base_year - 3)
        sta = sp.get(base_year + 5) - sp.get(base_year)
        need = ftab.loc[c, "adj_gap_mkt"] * 100
        cov = 1.0 if need <= 0 else max(sta, 0) / need
        effort = (rev + sta) / 2

        def band(x, bands):
            for k, t in enumerate(bands):
                if x >= t:
                    return k + 1
            return 5
        s = (band(effort, C.WILLINGNESS_EFFORT_BANDS) + band(cov, C.WILLINGNESS_COVERAGE_BANDS)) / 2
        rows[c] = {"Revealed: Δ structural PB, past 3y (pp)": rev, "Stated: IMF-projected Δ, next 5y (pp)": sta,
                   "Adjustment needed at market r (pp)": need, "Plan covers need": cov, "willingness": s}
    return pd.DataFrame(rows).T


@safe("Warning lights")
def s_warnings(data, ftab, rank, pol, base_year):
    W = C.WARN
    imf = data["imf"]
    d = data["daily"]
    today = pd.Timestamp(dt.date.today())

    def lvl(v, key, higher_worse=True):
        if v is None or pd.isna(v):
            return np.nan
        a, r = W[key]
        if higher_worse:
            return 2 if v > r else 1 if v > a else 0
        return 2 if v < r else 1 if v < a else 0

    fx_pairs = {"US": ("US10Y", "USD_BROAD", 1), "UK": ("UK10Y", "USD_PER_GBP", 1),
                "JP": ("JP10Y", "JPY_PER_USD", -1)}
    vals, lv = {}, {}
    for c in C.COUNTRIES:
        r = ftab.loc[c]
        m = C.AVG_MATURITY.get(c, 7)
        rp = np.array([r.eff_r + (r.mkt_r_10y - r.eff_r) * min(1, (t + 1) / m) for t in range(10)])
        path = F.project_debt(r.debt, rp, r.fwd_g, r.primary_bal, 10)
        i3 = C.ISO3[c]
        try:
            net_int = (imf["primary"][i3] - imf["overall"][i3]).get(base_year)
            rev = imf["revenue"][i3].get(base_year)
            int_rev = net_int / rev if rev else np.nan
        except Exception:  # noqa: BLE001
            int_rev = np.nan
        corr = np.nan
        if c in fx_pairs and {fx_pairs[c][0], fx_pairs[c][1]} <= set(d.columns):
            y, f, s = fx_pairs[c]
            x = d[[y, f]].dropna()
            x = pd.DataFrame({"y": x[y].diff(), "f": s * np.log(x[f]).diff()}).dropna().iloc[-60:]
            corr = x["y"].corr(x["f"]) if len(x) > 30 else np.nan
        try:
            days = (pd.Timestamp(pol.loc[c, "trigger_date"]) - today).days
        except Exception:  # noqa: BLE001
            days = np.nan
        vals[c] = {"r−g (mkt)": r.r_g_mkt, "Debt Δ 10y": path[-1] - path[0], "Req. PB vs best": r.gap_vs_best,
                   "Net interest / revenue": int_rev, "Priced percentile": rank.get(c, np.nan),
                   "Yield–FX corr (60d)": corr, "Political constraint": pol.loc[c, "political_constraint_1to5"],
                   "Days to trigger": days}
        lv[c] = {"r−g (mkt)": lvl(r.r_g_mkt, "r_g_mkt"), "Debt Δ 10y": lvl(path[-1] - path[0], "debt_10y_chg"),
                 "Req. PB vs best": lvl(r.gap_vs_best, "gap_vs_best"),
                 "Net interest / revenue": lvl(int_rev, "int_revenue"),
                 "Priced percentile": lvl(rank.get(c, np.nan), "priced_pctile"),
                 "Yield–FX corr (60d)": lvl(corr, "fx_yield_corr", higher_worse=False),
                 "Political constraint": lvl(pol.loc[c, "political_constraint_1to5"] + 1e-9, "politics"),
                 "Days to trigger": lvl(days, "trigger_days", higher_worse=False)}
    V, Lv = pd.DataFrame(vals).T, pd.DataFrame(lv).T
    fund_cols = ["r−g (mkt)", "Debt Δ 10y", "Req. PB vs best", "Net interest / revenue"]
    mkt_cols = ["Priced percentile", "Yield–FX corr (60d)"]
    pol_cols = ["Political constraint", "Days to trigger"]
    status, pillars = {}, {}
    for c in V.index:
        Fm = Lv.loc[c, fund_cols].max()
        Mm = Lv.loc[c, mkt_cols].max()
        Pm = Lv.loc[c, pol_cols].max()
        pillars[c] = (Fm, Mm, Pm)
        if Fm == 2 and Mm == 2 and Pm == 2:
            s = ("High", "Weak fundamentals, market stress and political risk together")
        elif Fm == 2 and Mm == 2:
            s = ("Elevated", "Weak fundamentals and markets are pricing it")
        elif Fm == 2 and Pm == 2:
            s = ("Elevated", "Weak fundamentals and a political trigger or inability to act")
        elif Fm == 2 and (Mm == 1 or Pm == 1):
            s = ("Moderate", "Weak fundamentals, early market or political pressure")
        elif Fm == 2:
            s = ("Moderate", "Weak fundamentals, no market or political pressure yet")
        elif Mm == 2:
            s = ("Moderate", "Market stress without weak fundamentals")
        else:
            s = ("Low", "")
        status[c] = s
    fmt = {"r−g (mkt)": "{:+.1%}", "Debt Δ 10y": "{:+.0%}", "Req. PB vs best": "{:+.1%}",
           "Net interest / revenue": "{:.0%}", "Priced percentile": "{:.0%}",
           "Yield–FX corr (60d)": "{:+.2f}", "Political constraint": "{:.1f}", "Days to trigger": "{:.0f}"}
    shade = {0: "#e8f5e9", 1: "#fff3cd", 2: "#f8d7da"}
    scol = {"High": "#e4606d", "Elevated": "#f5c6cb", "Moderate": "#ffe8a1", "Low": "#d4edda"}
    pname = {0: "green", 1: "amber", 2: "red"}
    maj = pol["majority_in_12m"].reindex(V.index) if "majority_in_12m" in pol else pd.Series(index=V.index, dtype=object)
    mcol = {"High": "#e8f5e9", "Medium": "#fff3cd", "Low": "#f8d7da"}
    groups = [("Fundamental", fund_cols), ("Market", mkt_cols),
              ("Political", ["Political constraint", "Days to trigger", "Majority in 12m"]),
              ("Summary", ["Fundamentals", "Market", "Politics"]), ("Overall", ["Risk", "Why"])]
    hdr1 = "<th></th>" + "".join(f'<th colspan="{len(cols)}" style="text-align:center">{g}</th>' for g, cols in groups)
    hdr = "".join(f"<th>{html.escape(k)}</th>" for k in list(V.columns) + ["Majority in 12m", "Fundamentals", "Market",
                                                                            "Politics", "Risk", "Why"])
    rows = ""
    for c in V.index:
        cells = ""
        for k in V.columns:
            v, l_ = V.loc[c, k], Lv.loc[c, k]
            txt = "n/a" if pd.isna(v) else fmt[k].format(v)
            bg = shade.get(int(l_), "#fff") if pd.notna(l_) else "#f4f4f4"
            cells += f'<td style="background:{bg}">{txt}</td>'
        mj = maj.get(c, "")
        mj = "" if pd.isna(mj) else str(mj)
        cells += f'<td style="background:{mcol.get(mj, "#fff")}">{html.escape(mj + (" (sweep)" if c == "US" and mj else ""))}</td>'
        for lvl_ in pillars[c]:
            l2 = int(lvl_) if pd.notna(lvl_) else 0
            cells += f'<td style="background:{shade[l2]}">{pname[l2]}</td>'
        risk, why = status[c]
        cells += f'<td style="background:{scol.get(risk, "#fff")};font-weight:bold">{risk}</td>'
        cells += f'<td style="text-align:left;font-size:12px">{html.escape(why)}</td>'
        rows += f"<tr><th>{c}</th>{cells}</tr>"
    body = f'<div class="tbl"><table><tr>{hdr1}</tr><tr><th></th>{hdr}</tr>{rows}</table></div>'
    th = "; ".join([
        f"r−g amber >{W['r_g_mkt'][0]:+.0%}, red >{W['r_g_mkt'][1]:+.0%}",
        f"debt Δ amber >{W['debt_10y_chg'][0]:+.0%}, red >{W['debt_10y_chg'][1]:+.0%}",
        f"PB gap amber >{W['gap_vs_best'][0]:+.0%}, red >{W['gap_vs_best'][1]:+.0%}",
        f"interest/revenue amber >{W['int_revenue'][0]:.0%}, red >{W['int_revenue'][1]:.0%}",
        f"priced amber >{W['priced_pctile'][0]:.0%}, red >{W['priced_pctile'][1]:.0%}",
        f"yield–FX corr amber <{W['fx_yield_corr'][0]}, red <{W['fx_yield_corr'][1]}",
        f"trigger amber <{W['trigger_days'][0]}d, red <{W['trigger_days'][1]}d",
        f"political constraint amber ≥{W['politics'][0]:.0f}, red ≥{W['politics'][1]:.0f}"])
    section("Warning lights", body,
            "Fixed thresholds rather than rankings, so a country can be red even if it is the best of the six. "
            "Each summary light is the worst of its "
            "indicators. Weak fundamentals are what make a country vulnerable; politics is the trigger or the "
            "inability to fix it; markets show whether investors are already charging for it. Risk is High when "
            "all three are red, Elevated when weak fundamentals meet either market stress or political risk, "
            "Moderate when there is one red light on its own or alongside early (amber) pressure, and Low "
            "otherwise. Majority in "
            "12m is context only and does not feed the risk level, since a majority can enable either consolidation "
            "or looser policy.",
            "Fundamental: r−g at market rates; debt change over 10 years if the effective rate converges to the "
            "market rate and the primary balance stays at its current level; required primary balance minus "
            "best 5-year record; IMF net interest / revenue (understates Japan's gross burden). Market: term "
            "premium (US/DE/UK/JP) or spread-to-Bund (FR/IT) percentile in own history; 60-day correlation of "
            "daily 10y yield and currency changes (not meaningful within the euro). Political: constraint "
            "composite (see Political calendar), days to the next binding election or budget deadline, and "
            "likelihood of a working majority in a year (US: one party controls presidency and both chambers), "
            "from manual/politics.csv. Thresholds: " + th
            + ". Editable in config.py.")


@safe("Debt dynamics (r − g)")
def s_dynamics(data, ftab, base_year):
    show = ftab[["debt", "primary_bal", "eff_r", "mkt_r_10y", "fwd_g", "r_g_eff", "r_g_mkt",
                 "req_pb_eff", "req_pb_mkt", "best_5y_pb", "adj_gap_mkt"]].copy()
    show.columns = ["Debt % GDP", "Primary bal", "Effective r", "Market r (10y)", "Fwd nominal g",
                    "r−g (eff)", "r−g (mkt)", "Req. PB (eff r)", "Req. PB (mkt r)",
                    "Best 5y avg PB", "Adjustment at mkt r"]
    pct = "{:.1%}"
    body = table_html(show, {c: pct for c in show.columns})
    fig = go.Figure()
    imf = data["imf"]["debt"]
    for c in C.COUNTRIES:
        s = imf[C.ISO3[c]].dropna()
        fig.add_scatter(x=s.loc[:base_year].index, y=s.loc[:base_year], name=f"{c}",
                        line=dict(color=COLORS[c]))
        fig.add_scatter(x=s.loc[base_year:].index, y=s.loc[base_year:], name=f"{c} IMF proj",
                        line=dict(color=COLORS[c], dash="dot"), showlegend=False)
        # own path: effective r converges to market r over average maturity, PB held flat
        r = ftab.loc[c]
        m = C.AVG_MATURITY.get(c, 7)
        rp = np.array([r.eff_r + (r.mkt_r_10y - r.eff_r) * min(1, (t + 1) / m) for t in range(10)])
        p = F.project_debt(r.debt, rp, r.fwd_g, r.primary_bal, 10) * 100
        fig.add_scatter(x=list(range(base_year, base_year + 11)), y=p, name=f"{c} at mkt r, PB flat",
                        line=dict(color=COLORS[c], dash="dash", width=1), showlegend=False)
    fig.update_layout(title="Gross debt, % GDP — solid: history, dotted: IMF, dashed: market r & flat PB",
                      xaxis=dict(range=[2000, base_year + 10]))
    body += fig_html(fig, 450)
    section("Debt dynamics (r − g)", body,
            "Required primary balance = the surplus that holds debt/GDP flat, d(r−g)/(1+g). Comparing it with "
            "the best 5-year record shows whether stabilising debt would need a consolidation the country has "
            "never sustained. Dashed lines show the debt path if the effective interest rate converges to "
            "today's market rate as debt rolls over and the primary balance stays where it is.",
            f"Base year {base_year} (IMF October WEO estimate). Forward g = IMF 5-year-ahead nominal growth unless "
            "LTCMA overrides are set in config.py. Market r = latest 10y yield. Primary balance is headline, not "
            "cyclically adjusted. Interest = primary minus overall balance, i.e. net interest, which understates "
            "the gross burden, especially for Japan.")


@safe("Term premium (ACM)")
def s_tp(data, tp, acm_res):
    tpm = tp.loc["1998":]
    body = ""
    m = acm_res["monthly"] if acm_res else None
    for mat, lab in ((120, "10y"), (360, "30y")):
        fig = go.Figure()
        for c in ["US", "DE", "UK", "JP"]:
            col = f"{c}_tp{mat}"
            if m is not None and col in m:
                s = m[col].loc["1998":] * 100
                fig.add_scatter(x=s.index, y=s, name=c, line=dict(color=COLORS[c]))
        if mat == 120 and "US_TP_ACM" in data["daily"]:
            ny = data["daily"]["US_TP_ACM"].dropna().resample("ME").last().loc["1998":] * 100
            fig.add_scatter(x=ny.index, y=ny, name="US — NY Fed ACM (check)",
                            line=dict(color=COLORS["US"], dash="dash", width=1))
        fig.update_layout(title=f"{lab} term premium, ACM model, bp (month-end)", yaxis_title="bp")
        body += fig_html(fig, 400)
    if acm_res and len(acm_res["latest"]):
        lt = acm_res["latest"].copy()
        show = pd.DataFrame({
            "As of": lt["date"].astype(str).str[:10],
            "10y yield": lt["y10"].astype(float), "10y risk-free": lt["rf10"].astype(float),
            "10y TP (bp)": lt["tp10"].astype(float) * 100,
            "30y yield": lt["y30"].astype(float), "30y TP (bp)": lt["tp30"].astype(float) * 100,
            "30y/10y TP": (lt["tp30"].astype(float) / lt["tp10"].astype(float)).where(lt["tp10"].astype(float).abs() > 0.2),
            "Sample from": lt["sample_start"]})
        body += "<h3>Latest (daily curve)</h3>" + table_html(show, {
            "10y yield": "{:.2f}", "10y risk-free": "{:.2f}", "10y TP (bp)": "{:.0f}",
            "30y yield": "{:.2f}", "30y TP (bp)": "{:.0f}", "30y/10y TP": "{:.1f}"})
    if acm_res and acm_res["notes"]:
        body += "<p class='warn'>" + html.escape("; ".join(acm_res["notes"])) + "</p>"

    section("Term premium (ACM)", body,
            "Term premium = the extra yield investors demand over the expected path of policy rates. A rising "
            "premium with stable rate expectations points to supply, fiscal or inflation-risk concerns rather "
            "than monetary policy. The 30y premium is where fiscal and supply pressure shows first.",
            "Adrian-Crump-Moench model as implemented by Bloomberg Economics: zero curves 1m–30y (Fed GSW, "
            "Bundesbank, BoE, Japan MoF par curve bootstrapped to zeros), 5 principal-component factors, VAR(1), "
            "three-step regressions on month-end data, applied to the latest daily curve; term premium = "
            "observed yield minus model risk-free yield. Samples: US from 1961, Germany 1998, UK 1996, Japan "
            "1992. Validation vs Bloomberg Economics' 10y estimates for 28 Jan 2026 (US 81bp, UK 123bp, DE "
            "112bp): this model's Jan-26 month-end is US ~54bp, UK ~138bp, DE ~115bp; the US gap reflects a "
            "different short rate and curve source (correlation with the NY Fed series 0.996). Japan: Aug-26 "
            "~220bp vs Bloomberg Intelligence BIFITPJP 238bp and Daiwa 184bp; samples starting after 1999 are "
            "dominated by the zero bound and should not be used. France: no free zero curve, see spreads.")
def _pctile(s: pd.Series) -> float:
    s = s.dropna()
    return float((s <= s.iloc[-1]).mean())


@safe("How much is priced")
def s_priced(data, acm_res, ftab):
    body = ""
    rank = {}
    if acm_res is not None and len(acm_res["monthly"]):
        m = acm_res["monthly"]
        lt = acm_res["latest"]
        rows = {}
        for c in C.TP_PRICED:
            if f"{c}_tp120" not in m:
                continue
            tp10 = (m[f"{c}_tp120"] * 100).loc["1998":].dropna()
            tp30 = (m[f"{c}_tp360"] * 100).loc["1998":].dropna()
            y10 = m[f"{c}_y120"].loc["1998":]
            vol = (m[f"{c}_y120"].diff().rolling(12).std() * np.sqrt(12) * 100).loc["1998":]
            now10 = float(lt.loc[c, "tp10"]) * 100 if c in lt.index else tp10.iloc[-1]
            now30 = float(lt.loc[c, "tp30"]) * 100 if c in lt.index else tp30.iloc[-1]
            p10 = float((tp10 <= now10).mean())
            rank[c] = p10
            rows[c] = {
                "10y TP now": now10, "Percentile since 1998": p10,
                "1998–07 avg": tp10.loc[:"2007"].mean(), "2012–19 avg": tp10.loc["2012":"2019"].mean(),
                "Peak": tp10.max(), "Peak date": tp10.idxmax().strftime("%b %Y"),
                "30y TP now": now30, "30y percentile": float((tp30 <= now30).mean()),
                "10y yield now / 98–07 / 12–19": f"{y10.dropna().iloc[-1]:.1f} / {y10.loc[:'2007'].mean():.1f} / {y10.loc['2012':'2019'].mean():.1f}",
                "Yield vol now / 98–07 (bp)": f"{vol.dropna().iloc[-1]:.0f} / {vol.loc[:'2007'].mean():.0f}",
            }
        body += table_html(pd.DataFrame(rows).T, {
            "10y TP now": "{:.0f}", "Percentile since 1998": "{:.0%}", "1998–07 avg": "{:.0f}",
            "2012–19 avg": "{:.0f}", "Peak": "{:.0f}", "30y TP now": "{:.0f}", "30y percentile": "{:.0%}"})

    y10 = data["y10"]
    dly = data["daily"]
    fig2 = go.Figure()
    srows = {}
    for c in ("FR", "IT"):
        if c in y10 and "DE" in y10:
            sp = ((y10[c] - y10["DE"]) * 100).loc["2008":].dropna()
            sp.index = sp.index + pd.offsets.MonthEnd(0)
            asof = sp.index[-1]
            if f"{c}10Y" in dly and "DE10Y_CNBC" in dly:
                w = ((dly[f"{c}10Y"] - dly["DE10Y_CNBC"]) * 100).dropna()
                if len(w):
                    sp = pd.concat([sp.loc[:w.index[0] - pd.Timedelta(days=1)], w])
                    asof = w.index[-1]
            fig2.add_scatter(x=sp.index, y=sp, name=f"{c}–DE", line=dict(color=COLORS[c]))
            monthly = sp.resample("ME").last()
            monthly.iloc[-1] = sp.iloc[-1]
            rank[c] = _pctile(monthly)
            srows[c] = {"10y spread to Bunds now (bp)": sp.iloc[-1], "As of": asof.strftime("%d %b %Y"),
                        "Percentile since 2008": rank[c],
                        "2012–19 avg": sp.loc["2012":"2019"].mean(), "Peak": sp.max(),
                        "Peak date": sp.idxmax().strftime("%b %Y")}
    fig2.update_layout(title="10y spread to Germany, bp (monthly to 2016, weekly since, latest live)")
    body += "<h3>France and Italy: spreads to Bunds</h3>" + fig_html(fig2, 330)
    body += table_html(pd.DataFrame(srows).T, {"10y spread to Bunds now (bp)": "{:.0f}",
                                               "Percentile since 2008": "{:.0%}", "2012–19 avg": "{:.0f}",
                                               "Peak": "{:.0f}"})
    section("How much is priced", body,
            "Where today's pricing sits in its own history. Percentiles show how unusual it is; the 1998–07 and "
            "2012–19 averages separate 'back to pre-QE normal' from 'beyond normal'; the yield and volatility "
            "columns show the rate backdrop, since pre-QE premia were earned at higher yields and inflation "
            "uncertainty. Descriptive only: no claim about what share is fiscal.",
            "US, Germany, UK, Japan: ACM 10y and 30y term premia, monthly since 1998, latest from the daily curve. "
            "France and Italy: 10y spread to Bunds since 2008 (OECD monthly averages to 2016, then CNBC weekly "
            "closes and the latest quote at the time of the daily run). The warning lights' priced "
            "percentile uses these.")
    return rank, {}


@safe("Triggers and market stress signals")
def s_triggers(data):
    body = ""
    d = data["daily"]
    if {"US10Y", "USD_BROAD"} <= set(d.columns):
        x = d[["US10Y", "USD_BROAD"]].dropna()
        corr = x["US10Y"].diff().rolling(60).corr(np.log(x["USD_BROAD"]).diff()).loc["2015":]
        fig = go.Figure(go.Scatter(x=corr.index, y=corr, name="US"))
        fig.add_hline(y=0, line_dash="dot")
        fig.update_layout(title="US: 60-day correlation of 10y yield changes with dollar index (DXY) changes")
        body += fig_html(fig, 320)
    m = pd.DataFrame(index=data["y10"].index)
    fx = d.resample("MS").mean()
    pairs = {"UK": ("UK", "USD_PER_GBP", 1), "JP": ("JP", "JPY_PER_USD", -1), "DE": ("DE", "USD_PER_EUR", 1)}
    fig2 = go.Figure()
    for lab, (c, f, sign) in pairs.items():
        if c in data["y10"] and f in fx:
            y = data["y10"][c].diff()
            ccy = sign * np.log(fx[f]).diff()
            cc = y.rolling(24).corr(ccy.reindex(y.index)).loc["2010":]
            fig2.add_scatter(x=cc.index, y=cc, name=lab, line=dict(color=COLORS[c]))
    fig2.add_hline(y=0, line_dash="dot")
    fig2.update_layout(title="24-month correlation: local 10y yield vs local currency (monthly)")
    body += fig_html(fig2, 320)
    if data.get("move") is not None:
        mv = data["move"].loc["2015":]
        fig3 = go.Figure(go.Scatter(x=mv.index, y=mv, name="MOVE"))
        fig3.update_layout(title="MOVE index (US rate volatility)")
        body += fig_html(fig3, 280)
    section("Triggers and market stress signals", body,
            "Yields rising while the currency falls is the classic fiscal-stress signature (UK 2022, US April "
            "2025), so a negative correlation is the warning sign. MOVE tracks US rate volatility.",
            "Daily yields: US Treasury, Bank of England, Japan MoF; FX and MOVE from Yahoo Finance. Not covered "
            "by free data: CDS, OIS swap spreads, auction tails, gross financing needs.")


@safe("Political calendar")
def s_politics(pol):
    fmt = {"Revealed: Δ structural PB, past 3y (pp)": "{:+.1f}", "Stated: IMF-projected Δ, next 5y (pp)": "{:+.1f}",
           "Adjustment needed at market r (pp)": "{:.1f}", "Plan covers need": "{:.0%}", "willingness": "{:.1f}",
           "political_constraint_1to5": "{:.1f}"}
    W = C.WARN

    def score(v):            # 1–5 scores, 5 = most constrained
        return 2 if v >= W["politics"][1] else 1 if v >= W["politics"][0] else 0

    def change(v):           # structural primary balance change, pp
        return 0 if v >= 1 else 1 if v >= 0 else 2

    def cover(v):
        return 0 if v >= 0.75 else 1 if v >= 0.5 else 2

    rules = {"political_constraint_1to5": score, "willingness": score, "track_record": score, "ability": score,
             "anchors": score, "Revealed: Δ structural PB, past 3y (pp)": change,
             "Stated: IMF-projected Δ, next 5y (pp)": change, "Plan covers need": cover,
             "majority_in_12m": lambda v: {"High": 0, "Medium": 1, "Low": 2}.get(v)}
    ren = {"political_constraint_1to5": "Political constraint", "willingness": "Willingness",
           "track_record": "Track record", "ability": "Ability", "anchors": "Anchors",
           "Revealed: Δ structural PB, past 3y (pp)": "Revealed effort, past 3y (pp)",
           "Stated: IMF-projected Δ, next 5y (pp)": "Planned effort, next 5y (pp)",
           "Adjustment needed at market r (pp)": "Needed at market r (pp)", "Plan covers need": "Plan covers need",
           "external_anchor": "External anchor", "next_binding_election": "Next election",
           "next_trigger": "Next trigger", "trigger_date": "Trigger date", "majority_in_12m": "Majority in 12m"}
    order = ["Political constraint", "Willingness", "Track record", "Ability", "Anchors",
             "Revealed effort, past 3y (pp)", "Planned effort, next 5y (pp)", "Needed at market r (pp)",
             "Plan covers need", "Majority in 12m", "Next election", "Next trigger", "Trigger date", "External anchor"]
    pol = pol.rename(columns=ren)
    pol = pol[[c for c in order if c in pol.columns]]
    rules = {ren.get(k, k): v for k, v in rules.items()}
    fmt = {ren.get(k, k): v for k, v in fmt.items()}
    section("Political calendar and capacity", styled_table(pol, fmt, rules),
            "Political constraint, 1–5 with 5 = most constrained, is a weighted average of four scores. "
            "Willingness is measured from data: revealed effort (change in the IMF structural primary balance "
            "over the past three years), stated effort (IMF-projected change over the next five, which builds "
            "in announced policies) and whether that plan covers the adjustment needed at market rates. Track "
            "record (has the country delivered before?), ability (majority, coalition cohesion, veto points) and "
            "external anchors (fiscal rules or conditional backstops; 5 = weak) are judgements. The composite, "
            "trigger dates and majority likelihood feed the warning lights.",
            "Structural primary balance = IMF structural balance (GGSB_NPGDP) plus net interest. Willingness = "
            "average of an effort score (mean of revealed and stated change: ≥+2pp → 1, ≥+1 → 2, ≥0 → 3, ≥−1 → 4, "
            "else 5) and a coverage score (stated change / need: ≥100% → 1, ≥75% → 2, ≥50% → 3, ≥25% → 4, else 5; "
            "1 if no adjustment is needed). Weights: " + ", ".join(f"{k.replace('_', ' ')} {v:.0%}" for k, v in C.POLITICS_WEIGHTS.items())
            + " (config.py). Track record, ability, anchors, election dates and majority ratings are judgements "
            "in manual/politics.csv. Dates marked approx. are estimates.")
# ----------------------------------------------------------------- page
CSS = """
:root{--bg:#fafafa;--fg:#1a1a1a;--muted:#666;--card:#fff;--line:#e3e3e3;--accent:#1f4e79}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.45}
header{background:var(--accent);color:#fff;padding:18px 24px}header h1{margin:0;font-size:22px}
header p{margin:4px 0 0;opacity:.85}nav{padding:8px 24px;background:#fff;border-bottom:1px solid var(--line);
position:sticky;top:0;z-index:5;overflow-x:auto;white-space:nowrap}nav a{margin-right:14px;color:var(--accent);
text-decoration:none;font-size:13px}main{max-width:1200px;margin:0 auto;padding:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:16px 20px;margin:16px 0}
h2{margin:0 0 8px;font-size:18px;color:var(--accent)}h3{font-size:15px}.note{color:var(--muted);font-size:12.5px}
.tbl{overflow-x:auto}table{border-collapse:collapse;font-size:13px;margin:8px 0}
th,td{padding:5px 9px;border-bottom:1px solid var(--line);text-align:right}th{background:#f3f5f8}
tr th:first-child{text-align:left}.err{background:#fff3f3;padding:8px;font-size:11px;overflow-x:auto}
.explain{margin:4px 0 10px}td.txt{text-align:left;font-size:12.5px}.details{margin-top:12px;border-top:1px solid var(--line);padding-top:8px}
.warn{background:#fff8e1;border:1px solid #f0d58a;padding:8px 12px;border-radius:4px}
"""


def render(mock: bool) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y %H:%M UTC")
    nav = "".join(f'<a href="#s{i}">{html.escape(s.split("<h2>")[1].split("</h2>")[0])}</a>'
                  for i, s in enumerate(SECTIONS))
    body = "".join(s.replace("<section>", f'<section id="s{i}">', 1) for i, s in enumerate(SECTIONS))
    warn = ""
    if mock:
        warn += '<p class="warn"><b>TEST PAGE — synthetic data, not real.</b></p>'
    if WARNINGS:
        warn += '<p class="warn">Some sections failed: ' + html.escape("; ".join(WARNINGS)) + "</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Fiscal Sustainability Monitor</title><style>{CSS}</style></head><body>
<header><h1>Fiscal Sustainability Monitor</h1><p>US · Germany · France · Italy · Japan · UK — updated {now}.
Public data only.</p></header><nav>{nav}</nav><main>{warn}{body}
<section><h2>Method notes</h2><p class="note">Sources: IMF World Economic Outlook (api.imf.org), OECD (monthly 10y yields
and 3m rates), US Treasury, NY Fed (ACM term premium), Bank of England, Bundesbank, Japan MoF (daily curves),
Yahoo Finance (FX, DXY, MOVE).
All modelling choices and calibrations are in config.py. This page is a research tool, not investment advice.</p></section>
</main></body></html>"""


def main():
    mock = "--mock" in sys.argv
    data = L.mock_all() if mock else L.load_all()
    base_year = dt.date.today().year
    pol = pd.read_csv(os.path.join(ROOT, "manual", "politics.csv")).set_index("country")

    ftab = safe("Fiscal table")(fiscal_table)(data, base_year)
    wts = C.POLITICS_WEIGHTS
    will = safe("Willingness")(willingness)(data, ftab, base_year) if ftab is not None else None
    if will is not None:
        pol.insert(0, "willingness", will["willingness"])
        for col in will.columns[:4][::-1]:
            pol.insert(0, col, will[col])
    else:
        pol.insert(0, "willingness", 3.0)
    pol.insert(0, "political_constraint_1to5", sum(pol[k] * w for k, w in wts.items()).round(1))
    acm_res = None
    if "curves" in data:
        acm_res = safe("ACM model")(TM.run_all)(data["curves"], data["y10"].attrs.get("oecd"))
    if acm_res is not None and len(acm_res["monthly"]):
        mm = acm_res["monthly"]
        tp = pd.DataFrame({c: mm[f"{c}_tp120"] * 100 for c in ["US", "DE", "UK", "JP"] if f"{c}_tp120" in mm})
        tp.index = tp.index.to_period("M").to_timestamp()
    else:
        tp = safe("Term premium proxies")(tp_proxies)(data)

    # build sections in display order; heatmap inserted at top afterwards
    s_health()
    if ftab is not None:
        s_dynamics(data, ftab, base_year)
    if tp is not None:
        s_tp(data, tp, acm_res)
    prob, sprob = ({}, {})
    if ftab is not None:
        r = s_priced(data, acm_res, ftab)
        if r:
            prob, sprob = r
    s_triggers(data)
    s_politics(pol)
    if ftab is not None:
        s_warnings(data, ftab, prob, pol, base_year)
        SECTIONS.insert(0, SECTIONS.pop())   # warning lights at the top

    os.makedirs(SITE, exist_ok=True)
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(render(mock))
    print(f"Wrote site/index.html — {len(SECTIONS)} sections, {len(WARNINGS)} warnings")
    for w in WARNINGS:
        print("  WARNING:", w)
    print("DATA HEALTH:")
    for name, status, last in L.HEALTH:
        print(f"  {name:40s} {status:60s} {last}")


if __name__ == "__main__":
    main()

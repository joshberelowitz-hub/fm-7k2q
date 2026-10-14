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


def section(title: str, body: str, note: str = "") -> None:
    n = f'<p class="note">{note}</p>' if note else ""
    SECTIONS.append(f"<section><h2>{html.escape(title)}</h2>{n}{body}</section>")


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


@safe("Overview heatmap")
def s_heatmap(ftab, prob, spreads_prob, pol):
    t = pd.DataFrame(index=C.COUNTRIES)
    t["Adjustment needed at market r"] = ftab["adj_gap_mkt"]
    t["Required PB vs best 5y record"] = ftab["gap_vs_best"]
    t["Political constraint"] = pol["political_constraint_1to5"].reindex(C.COUNTRIES)
    fund = F.heatmap(t)
    priced = pd.Series(prob, dtype=float).reindex(C.COUNTRIES)
    pr = np.ceil(priced * 5).clip(1, 5)
    fund["Priced (percentile vs own history)"] = pr
    fund["Fundamentals minus priced"] = (fund["composite"] - pr).round(1)

    def cell(v, col):
        if pd.isna(v):
            return "<td></td>"
        if col == "Fundamentals minus priced":
            colr = "#f8d7da" if v >= 1 else ("#d4edda" if v <= -1 else "#fff")
            return f'<td style="background:{colr}">{v:+.1f}</td>'
        shade = {1: "#e8f5e9", 2: "#f1f8e9", 3: "#fffde7", 4: "#ffe0b2", 5: "#ffccbc"}
        k = int(round(v)) if col != "composite" else int(round(v))
        return f'<td style="background:{shade.get(k, "#fff")}">{v:g}</td>'

    hdr = "".join(f"<th>{html.escape(c)}</th>" for c in fund.columns)
    rows = "".join(f"<tr><th>{i}</th>" + "".join(cell(fund.loc[i, c], c) for c in fund.columns) + "</tr>"
                   for i in fund.index)
    body = f'<div class="tbl"><table><tr><th></th>{hdr}</tr>{rows}</table></div>'
    section("Overview", body,
            "Scores 1–5, 5 = most stressed, ranked across these six countries. "
            "'composite' averages the three fundamentals columns (raw values in the sections below). 'Fundamentals minus priced' "
            "positive (red) = fundamentals rank worse than market pricing; negative (green) = market "
            "pricing is elevated relative to fundamentals. 'Priced' = percentile of today's term premium "
            "(US/DE/UK/JP, since 1998) or spread to Bunds (FR/IT, since 2008) in its own history, in quintiles.")


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
            f"Base year {base_year} (IMF estimate). Required PB = d(r−g)/(1+g). Forward g = IMF "
            "5-year-ahead nominal growth unless LTCMA overrides are set in config.py. Market r = latest "
            "10y yield. Primary balance is headline, not cyclically adjusted. Interest is backed out as "
            "primary minus overall balance, i.e. NET interest — this understates the gross burden, "
            "especially for Japan (large government financial assets, BoJ remittances).")


@safe("Cyclical sensitivity")
def s_cyclical(ftab):
    fig = go.Figure()
    end = {}
    for c in C.COUNTRIES:
        r = ftab.loc[c]
        sc = F.recession_scenario(r.debt, r.eff_r, r.fwd_g, r.primary_bal, 5, C.RECESSION_GAP_PATH,
                                  C.SEMI_ELASTICITY, C.R_BETA_TO_GAP_BP.get(c, 0))
        end[c] = sc["difference"].iloc[-1] * 100
        fig.add_scatter(y=sc["difference"] * 100, name=c, line=dict(color=COLORS[c]))
    fig.update_layout(title="Extra debt vs baseline in a standard recession (pp of GDP)",
                      xaxis_title="Years", yaxis_title="pp GDP")
    tbl = pd.DataFrame({"r beta (bp per pp gap)": C.R_BETA_TO_GAP_BP, "Extra debt after 5y (pp)": end})
    section("Cyclical sensitivity", fig_html(fig) + table_html(tbl, {"Extra debt after 5y (pp)": "{:.1f}"}),
            "Output gap path " + ", ".join(f"{g:.1%}" for g in C.RECESSION_GAP_PATH)
            + f"; semi-elasticity {C.SEMI_ELASTICITY}. Key asymmetry: safe havens get lower r in "
            "recession, spread countries get higher r. Edit betas in config.py.")


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
            "Adrian-Crump-Moench model as implemented by Bloomberg Economics: zero curves 1m–30y "
            "(Fed GSW, Bundesbank, BoE, Japan MoF bootstrapped), 5 principal-component factors, VAR(1), "
            "three-step regressions on month-end data, applied to the latest daily curve. Term premium = "
            "observed yield minus model risk-free yield. Validation vs Bloomberg Economics' published 10y "
            "estimates for 28 Jan 2026 (US 81bp, UK 123bp, DE 112bp): this model's Jan-26 month-end is "
            "US ~54bp, UK ~138bp, DE ~115bp; the US gap reflects a different short rate and curve source "
            "(correlation with the NY Fed series 0.996). Japan (MoF par curve bootstrapped to zeros, sample "
            "from 1992): Aug-26 month-end ~220bp vs Bloomberg Intelligence BIFITPJP 238bp (Daiwa's model: "
            "184bp). Samples starting after 1999 are dominated by the zero bound and should not be used. "
            "France: no free zero curve — see spreads.")


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
    fig2 = go.Figure()
    srows = {}
    for c in ("FR", "IT"):
        if c in y10 and "DE" in y10:
            sp = ((y10[c] - y10["DE"]) * 100).loc["2008":].dropna()
            fig2.add_scatter(x=sp.index, y=sp, name=f"{c}–DE", line=dict(color=COLORS[c]))
            rank[c] = _pctile(sp)
            srows[c] = {"10y spread to Bunds now (bp)": sp.iloc[-1], "Percentile since 2008": rank[c],
                        "2012–19 avg": sp.loc["2012":"2019"].mean(), "Peak": sp.max(),
                        "Peak date": sp.idxmax().strftime("%b %Y")}
    fig2.update_layout(title="10y spread to Germany, bp (monthly)")
    body += "<h3>France and Italy: spreads to Bunds</h3>" + fig_html(fig2, 330)
    body += table_html(pd.DataFrame(srows).T, {"10y spread to Bunds now (bp)": "{:.0f}",
                                               "Percentile since 2008": "{:.0%}", "2012–19 avg": "{:.0f}",
                                               "Peak": "{:.0f}"})
    section("How much is priced", body,
            "Descriptive only. US, Germany, UK, Japan: today's ACM term premium (bp) against its own "
            "monthly history since 1998, with the rate backdrop alongside — pre-QE premia were earned at "
            "higher yield levels and inflation uncertainty, so 1998–07 is not a pure 'normal'. France and "
            "Italy: 10y spread to Bunds since 2008. The heatmap's 'priced' column is the percentile.")
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
            "Negative yield–currency correlation (yields up, currency down) is the classic fiscal "
            "stress signature (UK 2022, US Apr 2025). Not covered by free data: CDS, OIS swap "
            "spreads, auction tails, gross financing needs.")


@safe("Political calendar")
def s_politics(pol):
    section("Political calendar and capacity", table_html(pol),
            "Edit manual/politics.csv. Political constraint 1–5, 5 = least able to consolidate.")


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
    if ftab is not None:
        s_cyclical(ftab)
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
        s_heatmap(ftab, prob, sprob, pol)
        SECTIONS.insert(0, SECTIONS.pop())   # heatmap goes to the top

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

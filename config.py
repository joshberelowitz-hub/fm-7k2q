"""
config.py — everything you might want to edit lives here.
After editing, the next daily run (or a manual "Run workflow") picks it up.
"""

# Countries shown on the page
COUNTRIES = ["US", "DE", "FR", "IT", "JP", "UK"]

# Extra markets used ONLY to build a cleaner global term premium factor
FACTOR_EXTRA = ["AU", "CA", "SE", "CH"]

# Countries used to build the global factor (FR/IT left out deliberately: their
# own stress would leak into everyone else's "global" factor)
TP_PRICED = ["US", "DE", "UK", "JP"]     # countries assessed on the ACM term premium lenses

ISO3 = {"US": "USA", "DE": "DEU", "FR": "FRA", "IT": "ITA", "JP": "JPN", "UK": "GBR",
        "AU": "AUS", "CA": "CAN", "SE": "SWE", "CH": "CHE"}
OECD2 = {"US": "US", "DE": "DE", "FR": "FR", "IT": "IT", "JP": "JP", "UK": "GB",
         "AU": "AU", "CA": "CA", "SE": "SE", "CH": "CH"}

# IMF WEO indicators (api.imf.org) (% of GDP or % change)
IMF_INDICATORS = {
    "debt": "GGXWDG_NGDP",
    "overall": "GGXCNL_NGDP",
    "primary": "GGXONLB_NGDP",
    "real_g": "NGDP_RPCH",
    "infl": "PCPIPCH",
    "revenue": "GGR_NGDP",
    "structural": "GGSB_NPGDP",
}

# --- Assumptions you will want to set ---------------------------------------

# Forward nominal g and r overrides (decimals), e.g. from LTCMAs.
# Leave empty to use IMF 5-year-ahead nominal growth and the latest 10y yield.
LTCMA_G = {}   # e.g. {"US": 0.040, "DE": 0.030}
LTCMA_R = {}

# Approximate average debt maturity (years): how fast effective r converges to market r
AVG_MATURITY = {"US": 6, "DE": 7, "FR": 8, "IT": 7, "JP": 9, "UK": 14}





# --- Warning lights: absolute thresholds (amber, red). Edit freely.
WARN = {
    "r_g_mkt":       (0.0, 0.01),    # r − g at market rates (decimal)
    "debt_10y_chg":  (0.10, 0.20),   # debt/GDP change over 10y at market r, primary balance flat
    "gap_vs_best":   (0.0, 0.02),    # required PB minus best 5-year average PB
    "int_revenue":   (0.10, 0.15),   # net interest / general government revenue
    "priced_pctile": (0.80, 0.95),   # term premium (US/DE/UK/JP) or spread to Bunds (FR/IT) percentile
    "fx_yield_corr": (-0.2, -0.4),   # 60-day correlation of daily yield and currency changes (lower = worse)
    "trigger_days":  (365, 182),     # days until next binding election / budget deadline (fewer = worse)
    "politics":      (3.0, 4.0),     # political constraint composite (1–5)
}

# Political constraint score: weights on the 1–5 sub-scores in manual/politics.csv (5 = most constrained)
POLITICS_WEIGHTS = {"willingness": 0.35, "track_record": 0.25, "ability": 0.25, "anchors": 0.15}

# Willingness (data-based): structural primary balance effort and how much of the need the plan covers
WILLINGNESS_EFFORT_BANDS = [2.0, 1.0, 0.0, -1.0]      # avg of revealed & stated change (pp): >= band -> score 1,2,3,4; else 5
WILLINGNESS_COVERAGE_BANDS = [1.0, 0.75, 0.5, 0.25]   # stated change / required adjustment: >= band -> 1,2,3,4; else 5

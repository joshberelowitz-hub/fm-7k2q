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
FACTOR_UNIVERSE = ["US", "DE", "UK"]   # countries that build the common term premium factor
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
}

# --- Assumptions you will want to set ---------------------------------------

# Forward nominal g and r overrides (decimals), e.g. from LTCMAs.
# Leave empty to use IMF 5-year-ahead nominal growth and the latest 10y yield.
LTCMA_G = {}   # e.g. {"US": 0.040, "DE": 0.030}
LTCMA_R = {}

# Approximate average debt maturity (years): how fast effective r converges to market r
AVG_MATURITY = {"US": 6, "DE": 7, "FR": 8, "IT": 7, "JP": 9, "UK": 14}

# Recession scenario: r response in bp per 1pp of output gap.
# Negative = r falls in recession (safe haven); positive = spreads widen.
R_BETA_TO_GAP_BP = {"US": -25, "DE": -25, "FR": 15, "IT": 40, "JP": -10, "UK": -10}
RECESSION_GAP_PATH = (-0.02, -0.03, -0.015, -0.005, 0.0)
SEMI_ELASTICITY = 0.5

# Stress episodes (country, month) used to define the "stressed" level of the
# idiosyncratic term premium. Probability = latest residual / average residual at these.
STRESS_EPISODES = [("UK", "2022-10"), ("US", "2023-10"), ("US", "2025-04")]

# Spread-to-Bund calibrations (bp): benign and stressed reference levels
SPREAD_CALIB = {
    "FR": {"benign": 40, "stressed": 250, "label": "Italy-2018-type spread"},
    "IT": {"benign": 100, "stressed": 300, "label": "Italy 2018"},
}

# Yield sensitivity to projected debt (bp per pp of debt/GDP), central and band
DEBT_ELASTICITY = 3.5
DEBT_ELASTICITY_BAND = (2.0, 5.0)

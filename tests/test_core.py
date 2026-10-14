import numpy as np, pandas as pd
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fiscal_core import *

# 1. dynamics: Italy-ish
print(required_adjustment(1.37, 0.035, 0.03, 0.01))
p = project_debt(1.0, 0.04, 0.03, 0.0, 10); print("10y path end", p[-1].round(3))
assert abs(project_debt(1.0, 0.04, 0.03, stabilising_pb(1.0,0.04,0.03), 5)[-1]-1.0) < 1e-12

# 2. fatigue: synthetic panel with known cubic
rng = np.random.default_rng(0)
d = pd.Series(rng.uniform(0.2, 1.6, 400))
pb = -0.02 + 0.12*d - 0.05*d**2 + 0.0*d**3 + rng.normal(0, 0.003, 400)
co = fit_reaction_function(pb, d); print({k: round(v,3) for k,v in co.items()})
print("debt limit", debt_limit(co, 0.04, 0.03))

# 3. recession
print(recession_scenario(1.37, 0.035, 0.03, 0.01, r_beta_to_gap_bp=30).round(3))

# 4. TP decomposition
idx = pd.date_range("2018-01-01", periods=300, freq="W")
g = np.cumsum(rng.normal(0, 3, 300))
tp = pd.DataFrame({c: b*g + rng.normal(0, 5, 300) for c, b in
                   zip(["US","DE","FR","IT","JP","UK"], [1.1,0.9,1.0,1.2,0.3,1.3])}, index=idx)
tp.loc[tp.index[-30:], "FR"] += 40   # idiosyncratic French shock
res = idiosyncratic_premium(tp); print("FR resid last", res["FR"].iloc[-5:].mean().round(1), "DE", res["DE"].iloc[-5:].mean().round(1))
print(betas_to_global(tp).round(2))
rr = idiosyncratic_premium(tp, window=52); print("rolling ok", rr.dropna().shape)
glob = global_factor(tp)
drivers = pd.DataFrame({"dm_debt": glob*0.5 + rng.normal(0,5,300), "move": rng.normal(100,10,300)}, index=idx)
print(decompose_global(glob, drivers, idx[0], idx[-1]).round(1))

# 5. priced
print(implied_stress_probability([20, 80, 600], 0, 200))
print(implied_debt_path(35, baseline_debt_pct=116))
print(market_rate_required_pb(1.16, 0.04, 0.03, 0.02, 0.005))

# 6. heatmap
t = pd.DataFrame({"adj_gap":[0.03,0.01,0.02,0.04,0.05],"political":[3,1,4,3,2],"priced_prob":[0.2,0.0,0.4,0.3,0.1]},
                 index=["US","DE","FR","IT","JP"])
print(heatmap(t, {"priced_prob": False}))
tp2 = tp.copy()
for c,b in zip(["AU","CA","SE","CH"],[1.0,1.0,0.9,0.6]): tp2[c] = b*g + rng.normal(0,5,300)
res2 = idiosyncratic_premium(tp2[["US","DE","FR","IT","JP","UK"]].join(tp2[["AU","CA","SE","CH"]]),
        factor_universe=["US","DE","JP","UK","AU","CA","SE","CH"])
print("broad universe FR", res2["FR"].iloc[-5:].mean().round(1), "DE", res2["DE"].iloc[-5:].mean().round(1))

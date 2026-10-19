"""How much do counties/regions deviate from a uniform statewide swing between real elections?"""
import numpy as np, pandas as pd
from common import load, statewide
c = load()
print(c.region.value_counts().to_string(), "\n")
print(c.groupby("region")[["sen24_total"]].sum().assign(pct=lambda d: (d.sen24_total / d.sen24_total.sum() * 100).round(1)).to_string(), "\n")
pairs = [("sen18", "sen24"), ("sen18", "gov22"), ("sen20", "sen24"), ("pres20", "pres24"), ("gov18", "gov22"), ("sen18", "sen20")]
rows = []
for a, b in pairs:
    sw = statewide(c, f"{b}_d2", f"{b}_total") - statewide(c, f"{a}_d2", f"{a}_total")
    resid = c[f"{b}_d2"] - (c[f"{a}_d2"] + sw)
    w = c[f"{b}_total"]
    reg = (resid * w).groupby(c.region).sum() / w.groupby(c.region).sum()
    within = resid - c.region.map(reg)
    big = c[f"{b}_total"] > 20000
    rows.append(dict(pair=f"{a}->{b}", state_swing=round(sw * 100, 2),
                     region_sd=round(np.sqrt(np.average(reg ** 2, weights=w.groupby(c.region).sum())) * 100, 2),
                     county_sd_big=round(np.sqrt(np.average(within[big] ** 2, weights=w[big])) * 100, 2),
                     **{r: round(v * 100, 1) for r, v in reg.items()}))
print(pd.DataFrame(rows).to_string(index=False))

"""For each Talarico county: the county margin at which his statewide win chance hits 95/90/70/50%."""
import numpy as np, pandas as pd
import simulate as S
from common import load

S.N_SIMS = 200_000
c, _ = S.build(load())
avg, _ = S.poll_average(pd.read_csv("data/polls.csv"))
r = S.simulate(c, avg, n=S.N_SIMS)
win = r["win"]
COUNTIES = ["Harris", "Dallas", "Tarrant", "Bexar", "Travis", "Collin", "Fort Bend", "Williamson",
            "El Paso", "Hidalgo", "Hays", "Nueces", "Cameron", "Jefferson", "Webb", "Denton"]

def crossing(m, w, level, window=4000):
    o = np.argsort(m); ms, ws = m[o], w[o].astype(float)
    roll = np.convolve(ws, np.ones(window) / window, mode="valid")
    mid = ms[window // 2: window // 2 + len(roll)]
    idx = np.where(roll >= level)[0]
    return mid[idx[0]] if len(idx) else np.nan

rows = []
for cn in COUNTIES:
    j = c.index[c.county == cn][0]
    m = (2 * r["share"][:, j] - 1) * 100
    rows.append(dict(county=cn, region=c.region[j], m18=(2 * c.sen18_d2[j] - 1) * 100, m24=(2 * c.sen24_d2[j] - 1) * 100,
                     forecast=np.median(m), p_county=(m > 0).mean() * 100,
                     lock95=crossing(m, win, .95), safe90=crossing(m, win, .90),
                     warn70=crossing(m, win, .70), coin50=crossing(m, win, .50)))
df = pd.DataFrame(rows)
df.to_csv("results/county_lines.csv", index=False)
f = lambda x: f"{'T' if x >= 0 else 'P'}+{abs(x):.1f}"
print(f"Statewide P(Talarico) = {win.mean()*100:.0f}%   ({S.N_SIMS:,} sims)\n")
print(f"{'County':<11}{'2018':>8}{'2024':>8}{'Forecast':>10}{'95% lock':>10}{'90% safe':>10}{'70% warn':>10}{'50% coin':>10}")
for _, x in df.iterrows():
    print(f"{x.county:<11}{f(x.m18):>8}{f(x.m24):>8}{f(x.forecast):>10}{f(x.lock95):>10}{f(x.safe90):>10}{f(x.warn70):>10}{f(x.coin50):>10}")

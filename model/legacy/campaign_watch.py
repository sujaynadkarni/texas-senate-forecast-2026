"""Campaign watch list: for each county, margin AND turnout levels where Talarico's statewide odds fall."""
import numpy as np, pandas as pd
import simulate as S
from common import load

S.N_SIMS = 200_000
c, _ = S.build(load())
avg, _ = S.poll_average(pd.read_csv("data/polls.csv"))
r = S.simulate(c, avg, n=S.N_SIMS)
win = r["win"].astype(float)

def crossing(x, w, level, window=5000, direction="up"):
    o = np.argsort(x); xs, ws = x[o], w[o]
    roll = np.convolve(ws, np.ones(window) / window, mode="valid")
    mid = xs[window // 2: window // 2 + len(roll)]
    idx = np.where(roll >= level)[0] if direction == "up" else np.where(roll <= level)[0]
    if not len(idx): return np.nan
    return mid[idx[0]] if direction == "up" else mid[idx[-1]]

rows = []
for j in c.index[c.exp_votes > 20000]:          # 70+ counties big enough to matter
    m = (2 * r["share"][:, j] - 1) * 100
    t = r["votes"][:, j] / c.exp_votes[j] * 100   # turnout as % of expected
    rows.append(dict(county=c.county[j], region=c.region[j], p=(m > 0).mean() * 100,
                     m18=(2 * c.sen18_d2[j] - 1) * 100, m24=(2 * c.sen24_d2[j] - 1) * 100, fc=np.median(m),
                     exp_k=c.exp_votes[j] / 1e3, votes18_k=c.sen18_total[j] / 1e3,
                     m_warn=crossing(m, win, .70), m_danger=crossing(m, win, .50),
                     t_warn=crossing(t, win, .70), t_danger=crossing(t, win, .50),
                     win_lo_turnout=win[t < 92].mean() * 100, win_hi_turnout=win[t > 108].mean() * 100))
df = pd.DataFrame(rows).sort_values("exp_k", ascending=False)
df.to_csv("results/campaign_watch.csv", index=False)
pd.set_option("display.width", 250)
print(df.round(1).to_string(index=False))

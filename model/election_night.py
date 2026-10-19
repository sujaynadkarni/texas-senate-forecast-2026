"""Election-night thresholds: given margins in the counties that have reported, when are we 80% sure?

Observed county margin = true final margin + noise, because the first dump is early+mail only:
  common early-vote skew N(0, 2 pts) shared by all counties + county noise N(0, 2.5 pts).
Index = vote-weighted average of (observed margin - forecast margin) across reported counties.
"""
import numpy as np, pandas as pd
import simulate as S
from common import load

N = 200_000
c, _ = S.build(load())
avg, _ = S.poll_average(pd.read_csv("data/polls.csv"))
r = S.simulate(c, avg, n=N)
win = r["win"].astype(float)
m = (2 * r["share"] - 1) * 100
fc = np.median(m, axis=0)
rng = np.random.default_rng(7)
obs = m + rng.normal(0, 2.0, (N, 1)) + rng.normal(0, 2.5, m.shape)

STAGES = {
    "1. Tarrant only": ["Tarrant"],
    "2. + Harris, Dallas, Bexar, Travis": ["Tarrant", "Harris", "Dallas", "Bexar", "Travis"],
    "3. + Collin, Denton, Fort Bend, Williamson": ["Tarrant", "Harris", "Dallas", "Bexar", "Travis", "Collin", "Denton", "Fort Bend", "Williamson"],
    "4. + El Paso, Hidalgo, Cameron, Montgomery": ["Tarrant", "Harris", "Dallas", "Bexar", "Travis", "Collin", "Denton", "Fort Bend", "Williamson",
                                                    "El Paso", "Hidalgo", "Cameron", "Montgomery"],
}

def crossing(x, w, level, window=5000):
    o = np.argsort(x); xs, ws = x[o], w[o]
    roll = np.convolve(ws, np.ones(window) / window, mode="valid")
    mid = xs[window // 2: window // 2 + len(roll)]
    return mid[np.where(roll >= level)[0][0]]

for stage, names in STAGES.items():
    idx = [c.index[c.county == n][0] for n in names]
    wts = c.exp_votes.values[idx]
    dev = ((obs[:, idx] - fc[idx]) * wts).sum(1) / wts.sum()
    share = wts.sum() / c.exp_votes.sum() * 100
    p80, p50, p20 = crossing(dev, win, .80), crossing(dev, win, .50), crossing(dev, win, .20)
    decided = ((dev > p80) | (dev < p20)).mean() * 100
    print(f"\n{stage}  ({share:.0f}% of expected vote)")
    print(f"   vs forecast: Paxton 80% if below {p20:+.1f} | coin flip at {p50:+.1f} | Talarico 80% if above {p80:+.1f}"
          f"   -> 80% call possible in {decided:.0f}% of nights")
    if len(names) <= 5:
        for n, i in zip(names, idx):
            print(f"      {n:<9} forecast {fc[i]:+.1f}:  Paxton-80% below {fc[i]+p20:+.1f} | Talarico-80% above {fc[i]+p80:+.1f}")

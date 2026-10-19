"""Backtest: run the same model 'as of' 2018 and 2024 using only earlier data + that year's final poll average."""
import numpy as np, pandas as pd
import simulate as S
lab = lambda x: S.fmt_m(x).replace("Talarico", "Dem").replace("Paxton", "Rep")
from common import load, statewide

def run(c, year, base_a, base_b, rate_from, reg_now, poll_d2, actual):
    c = c.copy()
    for b in (base_a, base_b):
        c[f"rel_{b}"] = c[f"{b}_d2"] - statewide(c, f"{b}_d2", f"{b}_total")
    c["rel_bt"] = 0.5 * c[f"rel_{base_a}"] + 0.5 * c[f"rel_{base_b}"]
    c["primary_adj"] = 0.0
    c["exp_votes"] = c[reg_now] * c[f"{rate_from}_total"] / c[f"reg{rate_from[-2:]}"]
    r = S.simulate(c, poll_d2, pattern="rel_bt")
    pred = r["share"].mean(0)
    act = c[f"{actual}_d2"].values
    w = c[f"{actual}_total"].values
    big = w > 20000
    called = ((r["share"] > .5).mean(0) > .5) == (act > .5)
    act_state = statewide(c, f"{actual}_d2", f"{actual}_total")
    lo, hi = np.percentile(r["state_share"], [10, 90])
    print(f"\n== {year}: pattern {base_a}+{base_b}, final poll avg {lab(poll_d2)}  ->  actual {lab(act_state)}")
    print(f"   P(Dem wins) = {r['win'].mean()*100:.1f}%   median {lab(np.median(r['state_share']))}   80% range {lab(lo)} .. {lab(hi)}"
          f"   actual inside 80% range: {lo <= act_state <= hi}")
    print(f"   County winners called correctly: {called.sum()}/254   (counties >20K votes: {called[big].sum()}/{big.sum()})")
    # county error after removing the statewide poll miss -> tests the county/region structure
    adj = pred + (act_state - np.average(pred, weights=c.exp_votes))
    err = (adj - act) * 200
    print(f"   County margin error, statewide miss removed: weighted mean abs {np.average(abs(err), weights=w):.1f} pts, big counties {np.average(abs(err[big]), weights=w[big]):.1f} pts")
    miss = pd.DataFrame({"county": c.county, "err": err, "w": w})[big].assign(a=lambda d: d.err.abs()).sort_values("a", ascending=False).head(5)
    print("   Biggest county misses (+ = model too Dem): " + ", ".join(f"{r.county} {r.err:+.1f}" for _, r in miss.iterrows()))
    # how well did the predicted interval cover?
    sd = r["share"].std(0)
    cover = (abs(adj - act) < 1.2816 * sd)
    print(f"   Counties inside their own 80% interval (after statewide miss removed): {cover.mean()*100:.0f}%")

c = load()
c["reg_now18"] = c.reg18; c["reg_now24"] = c.reg24
run(c, 2018, "sen14", "pres16", "sen14", "reg18", 0.5 - 0.0588 / 2, "sen18")   # Cruz +5.9 avg (16 polls, Oct)
run(c, 2024, "sen18", "sen20", "sen20", "reg24", 45.4 / (45.4 + 49.4), "sen24")                                        # Cruz +4.0 avg

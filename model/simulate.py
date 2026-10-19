"""Texas Senate 2026 (Talarico vs Paxton) county-level Monte Carlo.

Shares are Democratic two-party share (Talarico / (Talarico + Paxton)).
Run from project root:  PYTHONPATH=model python3 model/simulate.py
"""
import re, json, numpy as np, pandas as pd
from datetime import date, datetime
from zoneinfo import ZoneInfo
from common import load, statewide

N_SIMS = 50_000
RNG = np.random.default_rng(2026)
AS_OF = datetime.now(ZoneInfo("America/Chicago")).date()     # Texas time, also on GitHub's UTC servers
REG_2026 = 19_041_684                       # Texas SOS, Oct 16 2026

# ---- uncertainty settings (calibrated in calibrate.py / historical TX poll misses) -------------
POLL_ERR_SD = 0.0225      # statewide two-party share; ~4.5 pts on margin (2018/20/24 misses: 3.3, 3.1, 4.5)
POLL_ERR_DF = 5           # fat tails
POLL_BIAS = 0.0           # mean poll miss (+ = toward Talarico). Stress test uses R-favoring bias.
REGION_SD = {"Urban core": 0.020, "Big suburbs": 0.022, "Outer suburbs": 0.020,
             "Hispanic South/West": 0.040, "Mid-size metros": 0.020, "Rural": 0.020}
COUNTY_SD = 0.018      # widened after 2018 backtest (only 33% of counties inside 80% band at 1.3)
TURNOUT_STATE_SD, TURNOUT_REGION_SD, TURNOUT_COUNTY_SD = 0.07, 0.05, 0.03
PRIMARY_SIGNAL_WEIGHT = 0.15   # how much of the 2026 primary-turnout shift (vs 2022) to trust, by region


# ---- poll average -----------------------------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                      "August", "September", "October", "November", "December"], 1)}

def end_date(s):
    parts = re.findall(r"(January|February|March|April|May|June|July|August|September|October|November|December)?\s*(\d+)", s.split(",")[0])
    month = None
    for m, d in parts:
        if m: month = m
        day = int(d)
    return date(int(re.findall(r"20\d\d", s)[-1]), MONTHS[month], day)

def poll_average(polls):
    p = polls.copy()
    p["end"] = p.dates.map(end_date)
    p["age"] = p.end.map(lambda d: (AS_OF - d).days)
    p["pollster"] = p.pollster.str.replace(r"<br\s*/>|<!--.*?-->", "", regex=True).str.strip()
    # one row per poll: prefer LV over RV
    p["lv"] = p["pop"].str.contains("LV")
    p = p.sort_values("lv", ascending=False).drop_duplicates(["pollster", "dates"])
    p = p[p.age <= 60]
    p["d2"] = p.d / (p.d + p.r)                    # Democrat's two-party share
    n = p.n.fillna(800).clip(upper=2000)
    partisan = p.pollster.str.contains(r"\((?:R|D)\)")
    # each pollster's repeated polls share weight so one firm can't dominate
    per_firm = p.groupby("pollster").pollster.transform("count")
    p["w"] = 0.5 ** (p.age / 14) * np.sqrt(n) * np.where(partisan, 0.6, 1.0) / np.sqrt(per_firm)
    return float(np.average(p.d2, weights=p.w)), p.sort_values("end", ascending=False)


# ---- county baseline ------------------------------------------------------------------------
def build(c, bases=("sen18", "sen24")):
    """bases: two past races whose county pattern (lean relative to the state) is blended 50/50."""
    a, b = bases
    c["rel_a"] = c[f"{a}_d2"] - statewide(c, f"{a}_d2", f"{a}_total")       # county lean relative to state
    c["rel_b"] = c[f"{b}_d2"] - statewide(c, f"{b}_d2", f"{b}_total")
    c["rel_blend"] = 0.5 * c.rel_a + 0.5 * c.rel_b
    # 2026 primary signal: change in Dem share of primary voters vs 2018, region relative to state
    st = lambda col, y: (c[col] * (c[f"dem_primary{y}"] + c[f"rep_primary{y}"])).groupby(c.region).sum() / \
                        (c[f"dem_primary{y}"] + c[f"rep_primary{y}"]).groupby(c.region).sum()
    tot = lambda y: c[f"dem_primary{y}"].sum() / (c[f"dem_primary{y}"].sum() + c[f"rep_primary{y}"].sum())
    reg_shift = (st("dprim_share26", "26") - tot("26")) - (st("dprim_share22", "22") - tot("22"))
    c["primary_adj"] = c.region.map(reg_shift * PRIMARY_SIGNAL_WEIGHT)
    # expected 2026 turnout: 2018 county turnout rate (last high-energy midterm) x 2026 registration
    c["reg26"] = c.reg24 * REG_2026 / c.reg24.sum()
    try:                                       # exact county registration from the SOS early-vote feed
        reg = {k: v["registered"] for k, v in json.load(open("data/turnout.json"))["counties"].items()}
        c["reg26"] = c.county.map(reg).fillna(c.reg26)
    except (OSError, KeyError, ValueError):
        pass
    c["rate18"] = c.sen18_total / c.reg18
    c["exp_votes"] = c.reg26 * c.rate18
    return c, reg_shift


def simulate(c, target, bias=POLL_BIAS, pattern="rel_blend", n=N_SIMS, extra_region_shift=None):
    regions = sorted(c.region.unique())
    ridx = c.region.map({r: i for i, r in enumerate(regions)}).values
    k = len(c)
    base_rel = c[pattern].values + c.primary_adj.values
    exp_v = c.exp_votes.values
    # statewide draw
    state = target + bias + POLL_ERR_SD * RNG.standard_t(POLL_ERR_DF, n) / np.sqrt(POLL_ERR_DF / (POLL_ERR_DF - 2))
    reg_sd = np.array([REGION_SD[r] for r in regions])
    reg_dev = RNG.normal(0, 1, (n, len(regions))) * reg_sd
    if extra_region_shift:
        for r, v in extra_region_shift.items(): reg_dev[:, regions.index(r)] += v
    share = base_rel[None, :] + reg_dev[:, ridx] + RNG.normal(0, COUNTY_SD, (n, k))
    # re-center so that at expected turnout the statewide share equals the statewide draw
    cur = (share * exp_v).sum(1) / exp_v.sum()
    share = np.clip(share + (state - cur)[:, None], 0.02, 0.98)
    # turnout noise (this is real signal on top of the polls: who actually shows up)
    t_mult = (1 + TURNOUT_STATE_SD * RNG.normal(0, 1, n))[:, None] * \
             (1 + TURNOUT_REGION_SD * RNG.normal(0, 1, (n, len(regions))))[:, ridx] * \
             (1 + TURNOUT_COUNTY_SD * RNG.normal(0, 1, (n, k)))
    votes = exp_v[None, :] * np.clip(t_mult, 0.5, 1.6)
    d = share * votes
    state_share = d.sum(1) / votes.sum(1)
    return dict(share=share, votes=votes, state_share=state_share, win=state_share > 0.5)


def tipping_point(share, votes):
    """Median-voter county: line counties up from most-Talarico to most-Paxton; the county
    holding the 50th-percentile voter is the one whose result tracks the state's."""
    n, k = share.shape
    tp = np.empty(n, dtype=int)
    for i in range(n):
        order = np.argsort(-share[i])
        cum = np.cumsum(votes[i][order])
        tp[i] = order[np.searchsorted(cum, cum[-1] / 2)]
    return tp


def replay(c, share_col, rate_col):
    """Vote exactly like a past year (county shares + county turnout rates), with 2026 registration."""
    v = c.reg26 * c[rate_col]
    return float((c[share_col] * v).sum() / v.sum()), v


def needed_uniform_swing(c, share_col, votes):
    cur = (c[share_col] * votes).sum() / votes.sum()
    return 0.5 - cur


def needed_region_swing(c, share_col, votes, region):
    cur_d = (c[share_col] * votes).sum()
    need = votes.sum() / 2 - cur_d
    rv = votes[c.region == region].sum()
    return need / rv   # share points the region alone must move


def needed_core_turnout(c, share_col, rate_col, regions=("Urban core",)):
    """Turnout boost in Dem-core regions (others fixed) needed to flip, using a past year's shares."""
    for boost in np.arange(0, 1.01, 0.005):
        v = c.reg26 * c[rate_col] * np.where(c.region.isin(regions), 1 + boost, 1)
        if (c[share_col] * v).sum() / v.sum() > 0.5: return boost
    return None


def fmt_m(x):  # two-party share -> margin label
    m = (2 * x - 1) * 100
    return f"Talarico +{m:.1f}" if m >= 0 else f"Paxton +{-m:.1f}"

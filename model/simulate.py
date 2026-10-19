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
    p["d2"] = p.talarico / (p.talarico + p.paxton)
    n = p.n.fillna(800).clip(upper=2000)
    partisan = p.pollster.str.contains(r"\((?:R|D)\)")
    # each pollster's repeated polls share weight so one firm can't dominate
    per_firm = p.groupby("pollster").pollster.transform("count")
    p["w"] = 0.5 ** (p.age / 14) * np.sqrt(n) * np.where(partisan, 0.6, 1.0) / np.sqrt(per_firm)
    return float(np.average(p.d2, weights=p.w)), p.sort_values("end", ascending=False)


# ---- county baseline ------------------------------------------------------------------------
def build(c):
    s18 = statewide(c, "sen18_d2", "sen18_total")
    s24 = statewide(c, "sen24_d2", "sen24_total")
    c["rel18"] = c.sen18_d2 - s18               # county lean relative to state
    c["rel24"] = c.sen24_d2 - s24
    c["rel_blend"] = 0.5 * c.rel18 + 0.5 * c.rel24
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


def main():
    c = load()
    c, reg_shift = build(c)
    polls = pd.read_csv("data/polls.csv")
    avg, used = poll_average(polls)
    markets = pd.DataFrame(json.load(open("data/markets.json"))["markets"]).assign(notes=lambda d: d.volume_usd.map(lambda v: f"${v/1e6:.1f}M traded"))
    out = {}

    # --- main simulation
    res = simulate(c, avg)
    p_win = res["win"].mean()
    c["p_talarico"] = (res["share"] > 0.5).mean(0)
    c["exp_share"] = res["share"].mean(0)
    c["exp_votes_sim"] = res["votes"].mean(0)
    c["exp_net_D"] = ((2 * res["share"] - 1) * res["votes"]).mean(0)
    w, l = res["win"], ~res["win"]
    c["share_if_T_wins"] = res["share"][w].mean(0)
    c["share_if_P_wins"] = res["share"][l].mean(0)
    sub = RNG.choice(N_SIMS, 10_000, replace=False)
    tp = tipping_point(res["share"][sub], res["votes"][sub])
    c["tipping_pct"] = np.bincount(tp, minlength=len(c)) / len(sub)
    # leverage: net votes moved by a 1-pt swing in that county
    c["votes_per_pt"] = c.exp_votes_sim * 0.02

    # --- stress tests
    stress = {
        "Polls miss toward Paxton like 2024 (R+4.5 margin)": simulate(c, avg, bias=-0.0225)["win"].mean(),
        "Polls miss toward Paxton like 2020 (R+3.1 margin)": simulate(c, avg, bias=-0.0155)["win"].mean(),
        "Polls miss toward Talarico like 2018 (D+3.3 margin)": simulate(c, avg, bias=+0.0165)["win"].mean(),
        "County pattern = pure 2018": simulate(c, avg, pattern="rel18")["win"].mean(),
        "County pattern = pure 2024": simulate(c, avg, pattern="rel24")["win"].mean(),
        "South Texas snaps back halfway to 2018 (+4.7 pts)": simulate(c, avg, extra_region_shift={"Hispanic South/West": 0.047})["win"].mean(),
    }

    # --- replays: vote exactly like 2018 / 2024
    replays = {}
    for label, sc, rc_votes, rc_reg in (("2018 (Cruz vs O'Rourke)", "sen18_d2", "sen18_total", "reg18"),
                                         ("2024 (Cruz vs Allred)", "sen24_d2", "sen24_total", "reg24"),
                                         ("2022 AG (Paxton vs Garza)", "ag22_d2", "ag22_total", "reg22")):
        c["_rate"] = c[rc_votes] / c[rc_reg]
        sh, v = replay(c, sc, "_rate")
        replays[label] = dict(
            share=sh, votes=float(v.sum()),
            uniform=needed_uniform_swing(c, sc, v),
            region={r: needed_region_swing(c, sc, v, r) for r in ["Urban core", "Big suburbs", "Hispanic South/West", "Outer suburbs"]},
            core_turnout=needed_core_turnout(c, sc, "_rate"),
            core_sub_turnout=needed_core_turnout(c, sc, "_rate", ("Urban core", "Big suburbs")))

    # --- what the winning simulations look like, by region
    reg_rows = []
    for r in ["Urban core", "Big suburbs", "Outer suburbs", "Hispanic South/West", "Mid-size metros", "Rural"]:
        m = (c.region == r).values
        sv = res["votes"][:, m]; ss = res["share"][:, m]
        rs = (ss * sv).sum(1) / sv.sum(1)
        reg_rows.append(dict(region=r, counties=int(m.sum()), vote_pct=sv.sum(1).mean() / res["votes"].sum(1).mean(),
                             s18=statewide(c[m], "sen18_d2", "sen18_total"), s24=statewide(c[m], "sen24_d2", "sen24_total"),
                             exp=rs.mean(), if_T=rs[w].mean(), if_P=rs[l].mean(), prim_shift=reg_shift[r]))

    c.to_csv("results/county_forecast.csv", index=False)
    report(c, avg, used, markets, p_win, res, stress, replays, reg_rows)


def report(c, avg, used, markets, p_win, res, stress, replays, reg_rows):
    L = []
    P = L.append
    P("TEXAS SENATE 2026: TALARICO (D) vs PAXTON (R)")
    P(f"Model run {AS_OF}, {N_SIMS:,} simulations, 254 counties. Election Nov 3, 2026.\n")
    P("=" * 78)
    P("1. MARKETS")
    for _, m in markets.iterrows():
        P(f"   {m.source:<11} Talarico {m.talarico*100:.0f}%   Paxton {m.paxton*100:.0f}%   ({m.notes})")
    P("\n2. POLLS")
    P(f"   Model poll average (two-party): Talarico {avg*100:.1f}% / Paxton {(1-avg)*100:.1f}%  ->  {fmt_m(avg)}")
    P(f"   ({len(used)} polls in last 60 days, weighted by recency [14-day half-life], sample size;")
    P("    partisan-sponsored polls down-weighted, repeat pollsters share weight)")
    P("   Most recent 10:")
    for _, r in used.head(10).iterrows():
        P(f"     {r.end:%b %d}  {r.pollster[:38]:<38} {r['pop']:<3} T {r.talarico:.0f}  P {r.paxton:.0f}  ({'T' if r.margin_D>=0 else 'P'}+{abs(r.margin_D):.0f})")
    P("\n" + "=" * 78)
    P("3. MODEL RESULT")
    ss = res["state_share"]
    P(f"   Talarico wins {p_win*100:.1f}% of simulations   |   Paxton wins {(1-p_win)*100:.1f}%")
    P(f"   Median outcome: {fmt_m(np.median(ss))}")
    P(f"   80% range: {fmt_m(np.percentile(ss,10))}  to  {fmt_m(np.percentile(ss,90))}")
    tv = res["votes"].sum(1)
    P(f"   Expected turnout: {tv.mean()/1e6:.2f}M votes (80% range {np.percentile(tv,10)/1e6:.2f}M-{np.percentile(tv,90)/1e6:.2f}M)")
    P("\n   Stress tests (Talarico win %):")
    for k, v in stress.items(): P(f"     {k:<55} {v*100:5.1f}%")

    P("\n" + "=" * 78)
    P("4. COUNTY MAP DATA (probability Talarico carries each county)")
    bins = [(0, .05, "Safe Paxton (>95%)"), (.05, .25, "Likely Paxton"), (.25, .45, "Lean Paxton"),
            (.45, .55, "Toss-up"), (.55, .75, "Lean Talarico"), (.75, .95, "Likely Talarico"), (.95, 1.01, "Safe Talarico (>95%)")]
    for lo, hi, lab in bins:
        m = (c.p_talarico >= lo) & (c.p_talarico < hi)
        names = c[m].sort_values("exp_votes_sim", ascending=False).county.tolist()
        P(f"   {lab:<22} {m.sum():>3} counties, {c[m].exp_votes_sim.sum()/c.exp_votes_sim.sum()*100:4.1f}% of votes: "
          + ", ".join(names[:12]) + (" ..." if len(names) > 12 else ""))
    P("\n   Largest 25 counties:")
    P(f"     {'County':<12}{'Region':<21}{'2018':>10}{'2024':>10}{'Forecast':>13}{'P(T wins)':>11}{'Exp votes':>11}")
    for _, r in c.sort_values("exp_votes_sim", ascending=False).head(25).iterrows():
        P(f"     {r.county:<12}{r.region:<21}{fmt_m(r.sen18_d2).replace('Talarico','D').replace('Paxton','R'):>10}"
          f"{fmt_m(r.sen24_d2).replace('Talarico','D').replace('Paxton','R'):>10}"
          f"{fmt_m(r.exp_share).replace('Talarico','T').replace('Paxton','P'):>13}{r.p_talarico*100:>10.0f}%{r.exp_votes_sim/1e3:>10.0f}K")

    P("\n" + "=" * 78)
    P("5. KEY COUNTIES")
    P("   a) Vote banks - expected net votes:")
    top_d = c.sort_values("exp_net_D", ascending=False).head(8)
    top_r = c.sort_values("exp_net_D").head(8)
    P("      Talarico: " + ", ".join(f"{r.county} +{r.exp_net_D/1e3:.0f}K" for _, r in top_d.iterrows()))
    P("      Paxton:   " + ", ".join(f"{r.county} +{-r.exp_net_D/1e3:.0f}K" for _, r in top_r.iterrows()))
    rural = c[c.region == "Rural"].exp_net_D.sum()
    P(f"      (Paxton's 173 rural counties together: +{-rural/1e3:.0f}K net)")
    P("   b) Battlegrounds - counties with 15-85% chance either way, by size:")
    bg = c[(c.p_talarico > .15) & (c.p_talarico < .85)].sort_values("exp_votes_sim", ascending=False).head(12)
    for _, r in bg.iterrows():
        P(f"      {r.county:<12} P(T wins) {r.p_talarico*100:3.0f}%   forecast {fmt_m(r.exp_share):<14} {r.exp_votes_sim/1e3:5.0f}K votes   1pt swing = {r.votes_per_pt/1e3:.1f}K net votes")
    P("   c) Tipping-point counties (hold the median Texas voter: as they go, the state goes; % of sims):")
    for _, r in c.sort_values("tipping_pct", ascending=False).head(8).iterrows():
        P(f"      {r.county:<12} {r.tipping_pct*100:4.1f}%   ({r.region})")

    P("\n" + "=" * 78)
    P("6. IF TEXAS VOTES LIKE 2018 OR 2024 (exact county shares + turnout rates, 2026 registration)")
    for k, v in replays.items():
        P(f"\n   {k}: {fmt_m(v['share'])}   (~{v['votes']/1e6:.1f}M votes)  -> {'Talarico' if v['share']>0.5 else 'Paxton'} wins")
        P(f"     To flip it, Talarico needs:")
        P(f"       - a uniform swing of {v['uniform']*100:+.1f} pts in every county ({v['uniform']*200:+.1f} on margin), OR")
        for r, x in v["region"].items():
            P(f"       - {r} alone to move {x*100:+.1f} pts", )
        ct = v["core_turnout"]; cst = v["core_sub_turnout"]
        P(f"       - OR urban-core turnout up {ct*100:.0f}% (nothing else changes)" if ct is not None else "       - urban-core turnout alone can't do it")
        P(f"       - OR urban-core + big-suburb turnout up {cst*100:.0f}%" if cst is not None else "")

    P("\n" + "=" * 78)
    P("7. WHAT WINNING LOOKS LIKE, BY REGION (Talarico two-party share)")
    P(f"   {'Region':<21}{'Cnty':>5}{'Vote%':>7}{'2018':>8}{'2024':>8}{'Forecast':>10}{'T wins':>9}{'P wins':>9}{'Primary sig':>13}")
    for r in reg_rows:
        P(f"   {r['region']:<21}{r['counties']:>5}{r['vote_pct']*100:>6.1f}%{r['s18']*100:>7.1f}%{r['s24']*100:>7.1f}%"
          f"{r['exp']*100:>9.1f}%{r['if_T']*100:>8.1f}%{r['if_P']*100:>8.1f}%{r['prim_shift']*100:>+12.1f}")
    P("   'Primary sig' = change since 2022 in the region's Dem share of primary voters, relative to the state.")

    P("\n" + "=" * 78)
    P("8. ASSUMPTIONS & LIMITS")
    P("   - Statewide center = poll average; poll error SD 4.5 pts on margin, fat-tailed (Texas misses 2018-24: 3-4.5 pts).")
    P("   - County pattern = 50/50 blend of 2018 and 2024 Senate results relative to the state; regions drift together.")
    P("   - Region noise 2-2.2 pts (4 pts for Hispanic South/West, which swung ~9.5 pts 2018->2024); county noise 1.8 pts.")
    P("   - Turnout = 2018 county turnout rates x Oct 2026 registration (19.04M), +/-7% statewide, +/-5% by region.")
    P(f"   - 2026 primary turnout nudges regions ({PRIMARY_SIGNAL_WEIGHT:.0%} weight). SD-9 special (D+31 swing) not used directly.")
    P("   - Early vote turnout: in-person voting starts Oct 19; not yet in the model.")
    P("   - Third parties ignored (two-party shares).")
    open("results/forecast.txt", "w").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()

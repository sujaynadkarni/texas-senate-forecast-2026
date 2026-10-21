"""Run the model for every race in races.py and write site/data_<race>.json (everything the website shows).

Modes, picked automatically from the data:
  pre   - no votes cast yet                      -> needle = pre-election forecast
  early - early/mail turnout coming in, no count -> needle = forecast; turnout shown on the Early voting page
  live  - votes being counted                    -> needle = forecast updated by counted votes
  final - every county fully reported
Run from project root:  PYTHONPATH=model:pipeline python3 pipeline/export.py
"""
import json, os, sys
from datetime import datetime, timezone
import numpy as np, pandas as pd

sys.path[:0] = ["model", "pipeline"]
import simulate as S
from common import load, statewide
from races import RACES, margin_label
from early_vote import analyze as analyze_ev

N_SIMS = 50_000
POLL_WEIGHT = 1.0            # share of the statewide center taken from polls; the rest from the race's fundamentals
# Mail ballots lean Democratic in Harris (2024: mail D+41.0 vs county D+11.3 -> +14.9 pts of share).
# Elsewhere we have no county history, so assume a smaller lean. In-person early votes lean slightly D.
_h24 = [x for x in json.load(open("data/mail_history.json"))["harris"] if x["year"] == 2024][0]
MAIL_SKEW = {"Harris": (_h24["mail_margin_D"] - _h24["county_margin_D"]) / 200}
MAIL_SKEW_DEFAULT = 0.06
EV_SKEW = 0.008
REGIONS = ["Urban core", "Big suburbs", "Outer suburbs", "Hispanic South/West", "Mid-size metros", "Rural"]


def load_json(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def crossing(x, w, level, window=2500):
    """Value of x at which the rolling mean of w (sorted by x) first reaches `level`."""
    o = np.argsort(x); xs, ws = x[o], w[o].astype(float)
    roll = np.convolve(ws, np.ones(window) / window, mode="valid")
    mid = xs[window // 2: window // 2 + len(roll)]
    idx = np.where(roll >= level)[0]
    return float(mid[idx[0]]) if len(idx) else None


def pollster_leans(polls):
    """Sponsor (from the (R)/(D) tags) and house effect: how far a pollster's margins run from the
    average of other polls taken around the same time (10-day Gaussian window), shrunk toward 0."""
    p = polls.copy()
    p["end"] = p.dates.map(S.end_date)
    p = p[p.end.map(lambda d: d.year) == datetime.now().year]
    p["lv"] = p["pop"].astype(str).str.contains("LV")
    p = p.sort_values("lv", ascending=False).drop_duplicates(["pollster", "dates"])
    m = (p.d - p.r).values
    t = np.array([d.toordinal() for d in p.end])
    resid = []
    for i in range(len(p)):
        w = np.exp(-0.5 * ((t - t[i]) / 10) ** 2); w[i] = 0
        resid.append(m[i] - np.average(m, weights=w))
    p["resid"] = resid
    g = p.groupby("pollster").resid.agg(["mean", "count"])
    house = (g["mean"] * g["count"] / (g["count"] + 1)).to_dict()

    def sponsor(name):
        r, d = "(R)" in name, "(D)" in name
        return "Bipartisan" if r and d else "Republican" if r else "Democratic" if d else "Independent"
    return house, sponsor


def early_bias(counted, frac, mail, inperson, exp_votes, mail_skew):
    """Expected (counted share - final share) for a county, given that mail ballots and then
    in-person early votes are counted first. Fades to 0 as Election Day votes are added."""
    if counted <= 0 or frac >= 1:
        return 0.0
    early_total = max(mail + inperson, 0.6 * exp_votes)
    m_part = min(counted, mail)
    e_part = min(counted - m_part, max(early_total - mail, 0))
    E = m_part + e_part
    if E <= 0:
        return 0.0
    s_early = (m_part * mail_skew + e_part * EV_SKEW) / E
    final_votes = max(counted / max(frac, 1e-3), counted)
    x, D = counted - E, max(final_votes - E, 1)
    return s_early * E * max(0.0, 1 - x / D) / counted


def nowcast(c, res, results):
    """Update the simulations with counted votes (importance weighting, tempered to keep enough sims).
    results: {county: {d, r, precincts_reporting, precincts_total}}"""
    share, votes = res["share"], res["votes"]
    n, k = share.shape
    names = c.county.tolist()
    T = np.zeros(k); P = np.zeros(k); frac = np.zeros(k)
    for j, name in enumerate(names):
        r = results.get(name)
        if not r or (r["d"] + r["r"]) == 0:
            continue
        T[j], P[j] = r["d"], r["r"]
        f_prec = r["precincts_reporting"] / r["precincts_total"] if r.get("precincts_total") else 0
        f_vote = (T[j] + P[j]) / c.exp_votes.iloc[j]
        frac[j] = min(1.0, max(f_prec, min(f_vote, 0.98)))
    rep = (T + P) > 0
    if not rep.any():
        return None
    # mail and early ballots are counted first and lean bluer: remove the lean we expect in what is counted so far
    bias = np.array([early_bias(T[j] + P[j], frac[j], c.ev_mail.iloc[j] if "ev_mail" in c else 0,
                                (c.ev.iloc[j] - c.ev_mail.iloc[j]) if "ev" in c else 0, c.exp_votes.iloc[j],
                                MAIL_SKEW.get(names[j], MAIL_SKEW_DEFAULT)) for j in range(k)])
    obs = T[rep] / (T[rep] + P[rep]) - bias[rep]
    sd = 0.010 + 0.030 * (1 - frac[rep])                      # share pts: 2-8 pts on margin
    ll = -0.5 * (((share[:, rep] - obs) / sd) ** 2).sum(1)
    ll -= ll.max()
    beta, w = 1.0, None
    for beta in (1.0, 0.5, 0.25, 0.1, 0.05, 0.02, 0.01, 0.005):
        w = np.exp(beta * ll); w /= w.sum()
        if 1 / (w ** 2).sum() >= 2000:
            break
    # final count per sim: counted votes + simulated remaining votes
    counted = T + P
    remaining = np.clip(votes - counted[None, :], 0, None)
    remaining[:, frac >= 1.0] = 0
    d_final = T[None, :] + share * remaining
    tot_final = counted[None, :] + remaining
    st = d_final.sum(1) / tot_final.sum(1)
    order = np.argsort(st); cw = np.cumsum(w[order])
    q = lambda p: float(st[order][np.searchsorted(cw, p)])
    county_p = ((d_final / np.maximum(tot_final, 1) > 0.5) * w[:, None]).sum(0)
    return dict(p=float((w * (st > 0.5)).sum()), median=q(0.5), lo=q(0.1), hi=q(0.9),
                ess=float(1 / (w ** 2).sum()), temper=beta, county_p=county_p,
                expected_counted=float(counted.sum() / c.exp_votes.sum()),
                counted=float(counted.sum()), reported_counties=int(rep.sum()),
                complete_counties=int((frac >= 1.0).sum()), T=T, P=P, frac=frac)


def live_data(early, c):
    """Key counties, cumulative early votes so far (in person + mail), from the same county numbers the rest of
    the site uses (state counts plus county live counts for today). Compared with the same point of early voting
    in 2022 and 2018. A county appears once its total includes in-person votes."""
    from races import KEY_COUNTIES
    live = load_json("data/live.json") or {}
    reports = (load_json("data/county_reports.json") or {}).get("counties", {})
    if not early:
        return None
    E = early["counties"]
    group_of = {n: g for g, names in KEY_COUNTIES.items() for n in names}
    rows = []
    for name, g in group_of.items():
        if name == "Rural Texas":
            # only rural counties whose total already includes in-person votes, so the comparison is like for like
            es = [E[n] for n in c.county[c.region == "Rural"] if n in E and E[n]["in_person"] > 0 and not E[n]["missing"]]
            names = es
            ev, ip = sum(x["ev"] for x in es), sum(x["in_person"] for x in es)
            if ip <= 0:
                continue
            rows.append(dict(name=name, group=g, ev=ev, in_person=ip, mail=sum(x["mail"] for x in es),
                             today=sum(x["today"] for x in es), live=False, counties=len(names),
                             base={"2022": sum(x["ev22_raw"] for x in es), "2018": None, "2024": None}))
            continue
        x = E.get(name)
        if not x or x["in_person"] <= 0 or x["missing"]:      # not posted, or the state's file is clearly incomplete
            continue
        lv = (live.get("counties") or {}).get(name, {})
        rows.append(dict(name=name, group=g, ev=x["ev"], in_person=x["in_person"], mail=x["mail"], today=x["today"],
                         live=x.get("live", False), refreshed=lv.get("refreshed") if x.get("live") else None,
                         url=lv.get("url") or (reports.get(name, {}).get("url") if x.get("report") else None),
                         report=x.get("report", False), base={"2022": x["ev22_raw"] or None, "2018": x.get("ev18_raw"), "2024": None}))
    return dict(fetched=live.get("fetched"), day=early["day"], groups=KEY_COUNTIES, rows=rows)


def run_race(key, now, turnout, results_all, markets_all, fetch_log):
    race = RACES[key]
    D, R = race["d"], race["r"]
    ha, hb = race["bases"]
    c, _ = S.build(load(), bases=race["bases"])
    polls = pd.read_csv(f"data/polls_{key}.csv")
    poll_avg, used = S.poll_average(polls)
    center = POLL_WEIGHT * poll_avg + (1 - POLL_WEIGHT) * race["fundamentals"]

    S.RNG = np.random.default_rng(2026)
    res = S.simulate(c, center, n=N_SIMS)
    win = res["win"]
    ss = res["state_share"]
    m_county = (2 * res["share"] - 1) * 100
    c["p"] = (res["share"] > 0.5).mean(0)
    c["fc_margin"] = np.median(m_county, 0)
    c["lo_margin"], c["hi_margin"] = np.percentile(m_county, 10, 0), np.percentile(m_county, 90, 0)
    c["exp_votes_sim"] = res["votes"].mean(0)
    c["net"] = ((2 * res["share"] - 1) * res["votes"]).mean(0)
    c["exp_share"] = np.median(res["share"], 0)
    sub = np.random.default_rng(1).choice(N_SIMS, 10_000, replace=False)
    tp = S.tipping_point(res["share"][sub], res["votes"][sub])
    c["tipping"] = np.bincount(tp, minlength=len(c)) / len(sub)

    # symmetric county lines: below `r` the Republican is a 70% statewide favorite, at `even` it is a
    # coin flip, above `d` the Democrat is a 70% favorite
    lines = {}
    for j in c.index[c.exp_votes > 25000]:
        lines[c.county[j]] = dict(r=crossing(m_county[:, j], win, .30), even=crossing(m_county[:, j], win, .50),
                                  d=crossing(m_county[:, j], win, .70))

    ev = None
    if turnout:
        tc = turnout["counties"]
        c["ev"] = c.county.map(lambda n: tc.get(n, {}).get("in_person", 0) + tc.get(n, {}).get("mail", 0))
        c["ev_mail"] = c.county.map(lambda n: tc.get(n, {}).get("mail", 0))
        if c.ev.sum() > 0:
            ev = dict(as_of=turnout["as_of_date"], total=int(c.ev.sum()))
    early = analyze_ev(c, MAIL_SKEW, MAIL_SKEW_DEFAULT, EV_SKEW, names=(D, R))

    live = nowcast(c, res, results_all.get(key, {}))
    if live:
        mode = "final" if live["complete_counties"] == len(c) else "live"
        needle = dict(p=live["p"], median=live["median"], lo=live["lo"], hi=live["hi"])
        c["p_live"] = live["county_p"]
    else:
        mode = "early" if ev else "pre"
        needle = dict(p=float(win.mean()), median=float(np.median(ss)), lo=float(np.percentile(ss, 10)),
                      hi=float(np.percentile(ss, 90)))

    # scenarios: who wins, and what it would take for the other candidate (same math both ways)
    def what_it_takes(share, votes):
        d_wins = (share * votes).sum() / votes.sum() > 0.5
        trailer = R if d_wins else D
        need = S.needed_uniform_swing(c.assign(_s=share), "_s", votes)
        regs = ["Rural", "Outer suburbs"] if d_wins else ["Urban core", "Big suburbs"]
        region_moves = {g: float(S.needed_region_swing(c.assign(_s=share), "_s", votes, g)) for g in regs}
        boost = None                                                          # turnout rise in the trailer's base
        for b_ in np.arange(0, 1.01, 0.005):
            v = votes * np.where(c.region.isin(regs), 1 + b_, 1)
            if (((share * v).sum() / v.sum()) > 0.5) != d_wins:
                boost = float(b_); break
        sign = -1 if d_wins else 1                       # direction the trailer needs (+ = toward the Democrat)
        m_now = (2 * share - 1) * 100
        idx = {n: i for i, n in enumerate(c.county)}
        moved = lambda names, pts: [dict(name=n, before=round(float(m_now[idx[n]]), 1),
                                         after=round(float(m_now[idx[n]] + sign * pts), 1)) for n in names]
        uni = float(abs(need) * 200)
        biggest = lambda g, k=4: c[c.region == g].sort_values("exp_votes", ascending=False).county.head(k).tolist()
        return dict(trailer=trailer, uniform_pts=uni,
                    uniform_examples=moved(["Tarrant", "Collin", "Denton", "Harris"], uni),
                    regions=[dict(name=g, pts=float(abs(x) * 200), counties=int((c.region == g).sum()),
                                  examples=moved(biggest(g), float(abs(x) * 200)))
                             for g, x in region_moves.items()],                                     # margin points
                    turnout_regions=regs, turnout_boost=boost,
                    turnout_extra=None if boost is None else int(boost * votes[c.region.isin(regs).values].sum()))

    scenarios = [dict(label="Today's forecast", share=float(np.median(ss)), **what_it_takes(c.exp_share.values, c.exp_votes.values))]
    for h in race["history"]:
        yr = "reg" + h["key"][-2:]
        c["_rate"] = c[f"{h['key']}_total"] / c[yr]
        sh, v = S.replay(c, f"{h['key']}_d2", "_rate")
        scenarios.append(dict(label=f"Votes exactly like {h['label']}", share=sh, **what_it_takes(c[f"{h['key']}_d2"].values, v.values)))

    regions = []
    for g in REGIONS:
        m = (c.region == g).values
        sv, sh = res["votes"][:, m], res["share"][:, m]
        rs = (sh * sv).sum(1) / sv.sum(1)
        regions.append(dict(name=g, counties=int(m.sum()), vote_share=float(sv.sum(1).mean() / res["votes"].sum(1).mean()),
                            ha=float(2 * statewide(c[m], f"{ha}_d2", f"{ha}_total") - 1) * 100,
                            hb=float(2 * statewide(c[m], f"{hb}_d2", f"{hb}_total") - 1) * 100,
                            fc=float(np.median(2 * rs - 1) * 100)))


    counties = []
    for j, r in c.iterrows():
        row = dict(fips=r.fips, name=r.county, region=r.region, p=round(float(r.p), 4),
                   fc=round(float(r.fc_margin), 1), lo=round(float(r.lo_margin), 1), hi=round(float(r.hi_margin), 1),
                   ha=round(float(2 * r[f"{ha}_d2"] - 1) * 100, 1), hb=round(float(2 * r[f"{hb}_d2"] - 1) * 100, 1),
                   exp_votes=int(r.exp_votes_sim), net=int(r.net), tipping=round(float(r.tipping), 4),
                   registered=int(r.reg26))
        if r.county in lines:
            row["lines"] = {k: (round(v, 1) if v is not None else None) for k, v in lines[r.county].items()}
        if ev:
            row["ev"] = int(r.ev); row["ev_mail"] = int(r.ev_mail)
        if live:
            row["counted"] = dict(d=int(live["T"][j]), r=int(live["P"][j]), frac=round(float(live["frac"][j]), 3))
            row["p_live"] = round(float(r.p_live), 4)
        counties.append(row)

    hist_file = f"data/needle_history_{key}.json"
    history = load_json(hist_file, [])
    history.append(dict(t=now.isoformat(timespec="minutes"), p=round(needle["p"], 4), mode=mode))
    history = history[-500:]
    json.dump(history, open(hist_file, "w"))

    house, sponsor = pollster_leans(polls)
    out = dict(
        race=key, cand={k: race[k] for k in ("office", "d", "r", "d_full", "r_full", "d_init", "r_init", "context", "page")},
        history_races=race["history"],
        generated=now.isoformat(timespec="minutes"), mode=mode, n_sims=N_SIMS, poll_weight=POLL_WEIGHT,
        needle=needle, forecast=dict(p=float(win.mean()), median=float(np.median(ss)),
                                     lo=float(np.percentile(ss, 10)), hi=float(np.percentile(ss, 90)),
                                     turnout=float(res["votes"].sum(1).mean())),
        live=None if not live else {k: live[k] for k in ("p", "median", "lo", "hi", "ess", "expected_counted", "counted",
                                                          "reported_counties", "complete_counties")},
        polls=dict(average=poll_avg, n_used=int(len(used)),
                   recent=[dict(pollster=r.pollster, end=r.end.isoformat(), pop=r["pop"], n=None if pd.isna(r.n) else int(r.n),
                                d=r.d, r=r.r, sponsor=sponsor(r.pollster),
                                house=round(float(house.get(r.pollster, 0.0)), 1)) for _, r in used.head(15).iterrows()],
                   all=[dict(end=r.end.isoformat(), d=r.d, r=r.r, w=round(float(r.w), 3)) for _, r in used.iterrows()]),
        markets=markets_all.get(key, []), early_vote=ev, regions=regions, scenarios=scenarios, poll_history=race["poll_history"],
        history=history, counties=counties,
        fetch=fetch_log, mail_history=load_json("data/mail_history.json"),
        site_url=load_json("data/site.json", {}).get("url"),
        skew=dict(mail=MAIL_SKEW, mail_default=MAIL_SKEW_DEFAULT, early=EV_SKEW), early=early, live_turnout=live_data(early, c),
    )
    print(f"{key:<9} mode={mode}  needle={needle['p']*100:.1f}% {D}  polls={margin_label(key, (2*poll_avg-1)*100, True)}  "
          f"forecast median={margin_label(key, (2*np.median(ss)-1)*100, True)}")
    return out


def main():
    now = datetime.now(timezone.utc)
    turnout = load_json("data/turnout.json")
    results_all = load_json("data/results.json", {})
    markets_all = load_json("data/markets.json", {})
    fetch_log = load_json("data/fetch_log.json", {})
    outs = {k: run_race(k, now, turnout, results_all, markets_all, fetch_log) for k in RACES}

    # every race page knows the other races' county forecasts (split-ticket section) and early-vote leans
    for k, o in outs.items():
        o["others"] = {k2: dict(cand=o2["cand"], forecast=o2["forecast"], needle=o2["needle"],
                                counties={c["name"]: c["fc"] for c in o2["counties"]},
                                early=None if not o2["early"] else {x: o2["early"][x] for x in ("est_margin", "mix_effect_pts", "mix_effect_votes")}
                                | {"counties": {n: v["est_net"] for n, v in o2["early"]["counties"].items()}})
                       for k2, o2 in outs.items() if k2 != k}
    # the early-voting page shows both races' turnout effect
    effects = {k: dict(cand=o["cand"], **o["early"]["turnout_effect"]) for k, o in outs.items()
               if o["early"] and o["early"].get("turnout_effect")}
    for o in outs.values():
        if o["early"]:
            o["early"]["turnout_effects"] = effects
    # totals only go up: remember the highest in-person total per county for the day (see early_vote.load_floor)
    e = next((o["early"] for o in outs.values() if o["early"]), None)
    if e and e.get("floor_day"):
        floor = load_json("data/ev_floor.json", {})
        day = floor.setdefault(e["floor_day"], {})
        for n, x in e["counties"].items():
            if not x["missing"] and x["in_person"] > day.get(n, 0):
                day[n] = x["in_person"]
        json.dump(floor, open("data/ev_floor.json", "w"), separators=(",", ":"))
    os.makedirs("site", exist_ok=True)
    for k, o in outs.items():
        json.dump(o, open(f"site/data_{k}.json", "w"), separators=(",", ":"))
        print(f"site/data_{k}.json {os.path.getsize(f'site/data_{k}.json')/1024:.0f} KB")


if __name__ == "__main__":
    main()

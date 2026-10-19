"""Run the model on the latest inputs and write site/data.json (everything the website shows).

Modes, picked automatically from the data:
  pre   - no votes cast yet                      -> needle = pre-election forecast
  early - early/mail turnout coming in, no count -> needle = forecast; turnout pace shown
  live  - votes being counted                    -> needle = forecast updated by counted votes
  final - every county fully reported
Run from project root:  PYTHONPATH=model python3 pipeline/export.py
"""
import json, os, sys
from datetime import datetime, timezone
import numpy as np, pandas as pd

sys.path.insert(0, "model")
import simulate as S
from common import load, statewide

N_SIMS = 50_000
POLL_WEIGHT = 1.0            # share of the statewide center taken from polls; rest from FUNDAMENTALS
FUNDAMENTALS = 0.495         # Paxton +1: 2024 Cruz +8.5, minus ~6.5 midterm swing, minus ~1 Paxton penalty
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
    m = (p.talarico - p.paxton).values
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
    """Update the simulations with counted votes (importance weighting, tempered to keep enough sims)."""
    share, votes = res["share"], res["votes"]
    n, k = share.shape
    names = c.county.tolist()
    T = np.zeros(k); P = np.zeros(k); frac = np.zeros(k)
    for j, name in enumerate(names):
        r = results.get(name)
        if not r or (r["talarico"] + r["paxton"]) == 0:
            continue
        T[j], P[j] = r["talarico"], r["paxton"]
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


def main():
    now = datetime.now(timezone.utc)
    c, reg_shift = S.build(load())
    polls = pd.read_csv("data/polls.csv")
    poll_avg, used = S.poll_average(polls)
    center = POLL_WEIGHT * poll_avg + (1 - POLL_WEIGHT) * FUNDAMENTALS
    markets = load_json("data/markets.json", {"markets": []})
    turnout = load_json("data/turnout.json")
    results = load_json("data/results.json", {"counties": {}})["counties"]
    fetch_log = load_json("data/fetch_log.json", {})

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
    sub = np.random.default_rng(1).choice(N_SIMS, 10_000, replace=False)
    tp = S.tipping_point(res["share"][sub], res["votes"][sub])
    c["tipping"] = np.bincount(tp, minlength=len(c)) / len(sub)

    # county warning lines (statewide win chance 70% / 50%) and lock line (95%)
    lines = {}
    for j in c.index[c.exp_votes > 25000]:
        # symmetric: below `pax` Paxton is a 70% statewide favorite, at `even` it is a coin flip,
        # above `tal` Talarico is a 70% favorite
        lines[c.county[j]] = dict(pax=crossing(m_county[:, j], win, .30), even=crossing(m_county[:, j], win, .50),
                                  tal=crossing(m_county[:, j], win, .70))

    # early-vote pace: county share of early votes vs its share of expected final votes
    ev = None
    if turnout:
        tc = turnout["counties"]
        c["ev"] = c.county.map(lambda n: tc.get(n, {}).get("in_person", 0) + tc.get(n, {}).get("mail", 0))
        c["ev_mail"] = c.county.map(lambda n: tc.get(n, {}).get("mail", 0))
        tot_ev = c.ev.sum()
        if tot_ev > 0:
            c["ev_index"] = (c.ev / tot_ev) / (c.exp_votes / c.exp_votes.sum())
            reg_idx = {r: float((c.ev[c.region == r].sum() / tot_ev) / (c.exp_votes[c.region == r].sum() / c.exp_votes.sum()))
                       for r in REGIONS}
            ev = dict(as_of=turnout["as_of_date"], total=int(tot_ev), mail=int(c.ev_mail.sum()),
                      in_person=int(tot_ev - c.ev_mail.sum()), registered=int(c.reg26.sum()),
                      pct_of_expected=float(tot_ev / c.exp_votes.sum()), region_index=reg_idx,
                      mail_only=bool(c.ev_mail.sum() == tot_ev))

    c["exp_share"] = np.median(res["share"], 0)
    from early_vote import analyze as analyze_ev
    early = analyze_ev(c, MAIL_SKEW, MAIL_SKEW_DEFAULT, EV_SKEW)

    live = nowcast(c, res, results)
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
        trailer = "Paxton" if d_wins else "Talarico"
        need = S.needed_uniform_swing(c.assign(_s=share), "_s", votes)          # + = toward Talarico
        regs = ["Rural", "Outer suburbs"] if d_wins else ["Urban core", "Big suburbs"]
        region_moves = {r: float(S.needed_region_swing(c.assign(_s=share), "_s", votes, r)) for r in regs}
        boost = None                                                          # turnout rise in the trailer's base
        for b_ in np.arange(0, 1.01, 0.005):
            v = votes * np.where(c.region.isin(regs), 1 + b_, 1)
            if (((share * v).sum() / v.sum()) > 0.5) != d_wins:
                boost = float(b_); break
        return dict(trailer=trailer, uniform_pts=float(abs(need) * 200),
                    regions=[dict(name=r, pts=float(abs(x) * 200)) for r, x in region_moves.items()],      # margin points
                    turnout_regions=regs, turnout_boost=boost)

    scenarios = [dict(label="Today's forecast", share=float(np.median(ss)),
                      **what_it_takes(c.exp_share.values, c.exp_votes.values))]
    for label, sc, vcol, rcol in (("Votes exactly like 2018", "sen18_d2", "sen18_total", "reg18"),
                                  ("Votes exactly like 2024", "sen24_d2", "sen24_total", "reg24")):
        c["_rate"] = c[vcol] / c[rcol]
        sh, v = S.replay(c, sc, "_rate")
        scenarios.append(dict(label=label, share=sh, **what_it_takes(c[sc].values, v.values)))

    # replays + what it takes
    replays = []
    for label, sc, vcol, rcol in (("2018", "sen18_d2", "sen18_total", "reg18"), ("2024", "sen24_d2", "sen24_total", "reg24")):
        c["_rate"] = c[vcol] / c[rcol]
        sh, v = S.replay(c, sc, "_rate")
        ct = S.needed_core_turnout(c, sc, "_rate")
        replays.append(dict(year=label, share=sh, uniform=S.needed_uniform_swing(c, sc, v),
                            urban=S.needed_region_swing(c, sc, v, "Urban core"),
                            suburbs=S.needed_region_swing(c, sc, v, "Big suburbs"),
                            core_turnout=ct))

    stress = [dict(label="Polls are right on average", p=float(win.mean()))]
    for label, kw in (("Polls miss toward Paxton like 2024", dict(bias=-0.0225)),
                      ("Polls miss toward Paxton like 2020", dict(bias=-0.0155)),
                      ("Polls miss toward Talarico like 2018", dict(bias=+0.0165))):
        S.RNG = np.random.default_rng(11)
        stress.append(dict(label=label, p=float(S.simulate(c, center, n=20_000, **kw)["win"].mean())))

    regions = []
    for r in REGIONS:
        m = (c.region == r).values
        sv, sh = res["votes"][:, m], res["share"][:, m]
        rs = (sh * sv).sum(1) / sv.sum(1)
        regions.append(dict(name=r, counties=int(m.sum()), vote_share=float(sv.sum(1).mean() / res["votes"].sum(1).mean()),
                            m18=float(2 * statewide(c[m], "sen18_d2", "sen18_total") - 1) * 100,
                            m24=float(2 * statewide(c[m], "sen24_d2", "sen24_total") - 1) * 100,
                            fc=float(np.median(2 * rs - 1) * 100)))

    # histogram of statewide margins
    margins = (2 * ss - 1) * 100
    edges = np.arange(-16, 17, 1.0)
    hist, _ = np.histogram(np.clip(margins, -15.99, 15.99), bins=edges)

    counties = []
    for j, r in c.iterrows():
        row = dict(fips=r.fips, name=r.county, region=r.region, p=round(float(r.p), 4),
                   fc=round(float(r.fc_margin), 1), lo=round(float(r.lo_margin), 1), hi=round(float(r.hi_margin), 1),
                   m18=round(float(2 * r.sen18_d2 - 1) * 100, 1), m24=round(float(2 * r.sen24_d2 - 1) * 100, 1),
                   exp_votes=int(r.exp_votes_sim), net=int(r.net), tipping=round(float(r.tipping), 4),
                   registered=int(r.reg26))
        if r.county in lines:
            row["lines"] = {k: (round(v, 1) if v is not None else None) for k, v in lines[r.county].items()}
        if ev:
            row["ev"] = int(r.ev); row["ev_mail"] = int(r.ev_mail); row["ev_index"] = round(float(r.ev_index), 3)
        if live:
            row["counted"] = dict(t=int(live["T"][j]), p=int(live["P"][j]), frac=round(float(live["frac"][j]), 3))
            row["p_live"] = round(float(r.p_live), 4)
        counties.append(row)

    hist_file = "data/needle_history.json"
    history = load_json(hist_file, [])
    history.append(dict(t=now.isoformat(timespec="minutes"), p=round(needle["p"], 4), mode=mode))
    history = history[-500:]
    json.dump(history, open(hist_file, "w"))

    recent = used.head(15)
    house, sponsor = pollster_leans(polls)
    out = dict(
        generated=now.isoformat(timespec="minutes"), mode=mode, n_sims=N_SIMS, poll_weight=POLL_WEIGHT,
        needle=needle, forecast=dict(p=float(win.mean()), median=float(np.median(ss)),
                                     lo=float(np.percentile(ss, 10)), hi=float(np.percentile(ss, 90)),
                                     turnout=float(res["votes"].sum(1).mean())),
        live=None if not live else {k: live[k] for k in ("p", "median", "lo", "hi", "ess", "expected_counted", "counted",
                                                          "reported_counties", "complete_counties")},
        polls=dict(average=poll_avg, n_used=int(len(used)),
                   recent=[dict(pollster=r.pollster, end=r.end.isoformat(), pop=r["pop"], n=None if pd.isna(r.n) else int(r.n),
                                t=r.talarico, p=r.paxton, sponsor=sponsor(r.pollster),
                                house=round(float(house.get(r.pollster, 0.0)), 1)) for _, r in recent.iterrows()],
                   all=[dict(end=r.end.isoformat(), t=r.talarico, p=r.paxton, w=round(float(r.w), 3)) for _, r in used.iterrows()]),
        markets=markets.get("markets", []), early_vote=ev, regions=regions, replays=replays, scenarios=scenarios, stress=stress,
        histogram=dict(edges=edges.tolist(), counts=hist.tolist()), history=history, counties=counties,
        fetch=fetch_log, mail_history=load_json("data/mail_history.json"),
        site_url=load_json("data/site.json", {}).get("url"),
        skew=dict(mail=MAIL_SKEW, mail_default=MAIL_SKEW_DEFAULT, early=EV_SKEW), early=early,
    )
    os.makedirs("site", exist_ok=True)
    json.dump(out, open("site/data.json", "w"), separators=(",", ":"))
    print(f"mode={mode}  needle={needle['p']*100:.1f}%  forecast={win.mean()*100:.1f}%  polls={S.fmt_m(poll_avg)}  "
          f"early votes={ev['total'] if ev else 0:,}  size={os.path.getsize('site/data.json')/1024:.0f}KB")


if __name__ == "__main__":
    main()

"""Early-vote analysis: where ballots are coming from, how that compares with the same day in 2022,
and what the mix implies for each race.

Turnout files say how many people voted in each county, never whom they voted for. The partisan
read is an estimate: each county's ballots are assumed to split like the county is forecast to vote,
with mail ballots leaning further toward Democrats (Harris history) and in-person early votes slightly so.

2022 baseline: Texas Tribune early-voting tracker (Secretary of State data, all 254 counties, 12 days).
"""
import json
from datetime import date, datetime
import numpy as np, pandas as pd

EV_START = {2026: date(2026, 10, 19), 2022: date(2022, 10, 24)}
EV_DAYS = 12
REGIONS = ["Urban core", "Big suburbs", "Outer suburbs", "Hispanic South/West", "Mid-size metros", "Rural"]


def load_2022():
    rows = json.load(open("data/raw/ev_daily_2022_tt.json"))
    df = pd.DataFrame(rows)
    for col in ("reg_voters", "today_in_person", "cum_in_person", "cum_by_mail", "cum_ev_total", "ev_2018", "voted_2018", "reg_voters_2018"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["day"] = df["day"].astype(int)
    df["key"] = df.county.str.upper().str.replace(r"[^A-Z]", "", regex=True)
    return df


def load_2018():
    """30 largest counties, each day of 2018 early voting (Texas SOS daily reports)."""
    try:
        return {int(k): v for k, v in json.load(open("data/raw/ev_daily_2018_sos.json")).items()}
    except (OSError, ValueError):
        return {}


def load_live():
    try:
        return json.load(open("data/live.json"))
    except (OSError, ValueError):
        return None


def load_reports():
    try:
        return json.load(open("data/county_reports.json"))["counties"]
    except (OSError, ValueError, KeyError):
        return {}


def day_number(d):
    return max(0, (d - EV_START[2026]).days + 1)


def turnout_groups(c):
    """Counties grouped by the 2024 presidential result: early votes so far vs. the same point in 2022.
    Only counties whose 2026 numbers are complete are compared, on both sides."""
    if "ev26" not in c or c.ev26.sum() == 0:
        return None
    m24 = (c.pres24_D - c.pres24_R) / c.pres24_total * 100
    ok = ~c.missing & (c.ev22 > 0)
    bands = [("Trump by 20+", -999, -20, "rep"), ("Trump by less than 20", -20, 0, "lean-rep"),
             ("Harris won", 0, 999, "dem")]
    t26, t22 = c.ev26[ok].sum(), c.ev22[ok].sum()
    rows = []
    for name, lo, hi, cls in bands:
        m = ok & (m24 >= lo) & (m24 < hi)
        e26, e22 = float(c.ev26[m].sum()), float(c.ev22[m].sum())
        rows.append(dict(name=name, cls=cls, counties=int(((m24 >= lo) & (m24 < hi)).sum()), compared=int(m.sum()),
                         ev=int(e26), ev22=int(e22), pace=e26 / e22 if e22 else None,
                         share=e26 / t26 if t26 else None, share22=e22 / t22 if t22 else None))
    return dict(rows=rows, pace=float(t26 / t22) if t22 else None, compared=int(ok.sum()),
                not_posted=[n for n in c.sort_values("exp_votes", ascending=False).county[c.missing]][:8])


def turnout_effect(c, share_col):
    """How the turnout so far would move the forecast margin if every county keeps voting the way the forecast
    expects and keeps its turnout pace relative to 2022. Positive = toward the Democrat. The main forecast and
    needle do not use this."""
    if "ev26" not in c or c.ev26.sum() == 0:
        return None
    ok = ~c.missing & (c.ev22 > 0) & (c.ev26 > 0)
    if c.ev22[ok].sum() == 0:
        return None
    state_pace = c.ev26[ok].sum() / c.ev22[ok].sum()
    rel = (c.ev26 / c.ev22.where(c.ev22 > 0, 1)) / state_pace
    rel = 1 + (rel - 1) * c.ev22 / (c.ev22 + 2000)          # small counties: a few hundred votes say little
    rel = rel.where(ok, 1.0).clip(0.5, 2.0)                  # counties not posted yet: assume the state pace
    v0, share = c.exp_votes.values.astype(float), c[share_col].values
    v1 = v0 * rel.values
    m0 = ((2 * share - 1) * v0).sum() / v0.sum() * 100
    m1 = ((2 * share - 1) * v1).sum() / v1.sum() * 100
    return dict(points=round(float(m1 - m0), 2), forecast_margin=round(float(m0), 2), with_turnout=round(float(m1), 2),
                coverage=float(c.exp_votes[ok].sum() / c.exp_votes.sum()))


def primary_mix(c):
    """Early voters by 2026 primary (pipeline/primary_layer.py), only counties whose voter lists are mostly in:
    at least 75% of the state's official count for the county (lists trail the counts by a day or so), and the
    county's count itself not flagged incomplete."""
    try:
        pl = json.load(open("data/primary_layer.json"))
    except (OSError, ValueError):
        return None
    tot = dict(voters=0, dem=0, rep=0, both=0, none=0, dem_primary=0, dem_primary_voted=0, rep_primary=0, rep_primary_voted=0)
    used, counties = 0, {}
    for _, r in c.iterrows():
        x = pl["counties"].get(r.county)
        official = r.ev26 - (r.today26 if r.live else 0)          # state count, without today's live county numbers
        if not x or r.missing or official <= 0 or x["voters"] < 0.75 * official:
            continue
        used += 1
        counties[r.county] = x
        for k in tot:
            tot[k] += x.get(k, 0)
    if not tot["voters"]:
        return None
    share = {k: tot[k] / tot["voters"] for k in ("dem", "rep", "both", "none")}
    not_in = [n for n in c.sort_values("exp_votes", ascending=False).county if n not in counties][:6]
    # the headline: what share of each party's March 2026 (early/mail) primary voters have already voted this fall,
    # in the same counties
    rate = lambda k: tot[f"{k}_primary_voted"] / tot[f"{k}_primary"] if tot[f"{k}_primary"] else None
    turnout = dict(dem=rate("dem"), rep=rate("rep"), dem_base=tot["dem_primary"], rep_base=tot["rep_primary"],
                   dem_voted=tot["dem_primary_voted"], rep_voted=tot["rep_primary_voted"])
    return dict(fetched=pl["fetched"], through=pl["through"], counties_used=used, voters=tot["voters"], share=share, not_in=not_in,
                turnout=turnout,
                lean=(share["dem"] - share["rep"]) * 100, primary_early_voters=pl["primary_early_voters"],
                counties=counties)


def analyze(c, mail_skew, mail_default, ev_skew, share_col="exp_share", names=("Talarico", "Paxton")):
    """c: county frame with county, region, reg26, exp_votes, gov22_total, and the forecast share column."""
    try:
        daily = json.load(open("data/ev_daily_2026.json"))
    except (OSError, ValueError):
        return None
    if not daily:
        return None
    dates = sorted(daily, key=lambda s: datetime.strptime(s, "%m/%d/%Y"))
    latest = dates[-1]
    d_latest = datetime.strptime(latest, "%m/%d/%Y").date()
    n = day_number(d_latest)
    t22 = load_2022()
    c = c.copy()
    c["key"] = c.county.str.upper().str.replace(r"[^A-Z]", "", regex=True)
    cur = daily[latest]["counties"]
    c["in26"] = c.county.map(lambda x: cur.get(x, [0, 0, 0])[0]).astype(float)
    c["mail26"] = c.county.map(lambda x: cur.get(x, [0, 0, 0])[1]).astype(float)
    c["today26"] = c.county.map(lambda x: cur.get(x, [0, 0, 0])[2]).astype(float)
    # One set of numbers for the whole site: where the state has not posted today's in-person votes for a
    # county but the county's own live tracker has, use the county's count (unofficial) for today.
    # Official county reports that are ahead of the state's file (Tarrant's morning PDF): use them where the
    # state's in-person count for that county is lower.
    c["report"] = False
    reports = load_reports()
    for name, rec in reports.items():
        m = c.county == name
        if rec.get("error") or not rec.get("through") or not m.any() or rec["in_person"] <= float(c.loc[m, "in26"].iloc[0]):
            continue
        through = datetime.strptime(rec["through"], "%m/%d/%Y").date()
        if through > d_latest:
            continue                                  # the state's file is behind the report's day; wait for it
        c.loc[m, "in26"] = float(rec["in_person"])
        c.loc[m, "today26"] = float(rec["last_day"]) if through == d_latest else 0.0
        c.loc[m, "report"] = True
    c["live"] = False
    live = load_live()
    if live:
        live_day = datetime.strptime(live["date"], "%Y-%m-%d").date()
        if live_day >= d_latest:
            if live_day > d_latest:                      # the state has no file for today yet
                c["today26"] = 0.0
                n = day_number(live_day)
            # Official in-person total through the day before the live day. When the state already has a file for
            # the live day, it may hold part of that day (Travis: 1 vote; Bexar: part of the day with "0 today"),
            # so start from the previous day's file rather than add on top and double count.
            prev = daily[dates[-2]]["counties"] if live_day == d_latest and len(dates) > 1 else None
            for name, rec in live["counties"].items():
                m = c.county == name
                if rec.get("error") or not rec.get("today") or not m.any():
                    continue
                if live_day > d_latest:
                    base = float(c.loc[m, "in26"].iloc[0])
                elif prev is not None:
                    base = float(prev.get(name, [0, 0, 0])[0])
                else:
                    base = float(c.loc[m, "in26"].iloc[0] - c.loc[m, "today26"].iloc[0])
                total = base + rec["today"]
                if total <= float(c.loc[m, "in26"].iloc[0]):
                    continue                             # the official count is already ahead of the live one
                c.loc[m, "in26"] = total
                c.loc[m, "today26"] = float(rec["today"])
                c.loc[m, "live"] = True
    c["ev26"] = c.in26 + c.mail26
    if c.in26.sum() == 0:
        n = 0                       # no in-person votes yet: still the mail-only stretch before early voting

    # same point in 2022: day N (cumulative in-person + mail). Before early voting starts (day 0),
    # only mail exists, so compare with mail returned by the end of 2022's first day.
    base_day = max(1, n)
    b = t22[t22.day == base_day].set_index("key")
    final22 = t22[t22.day == EV_DAYS].set_index("key")
    c["reg22"] = c.key.map(b.reg_voters).fillna(0)
    # During the day most counties have not posted today's in-person votes yet. A county that has not
    # reported today is compared with 2022 through the previous day, so partial days are not unfair.
    if n == 0:
        c["reported_today"] = True
        c["ev22"] = c.key.map(b.cum_by_mail).fillna(0)
        c["mail22"] = c["ev22"]
    else:
        today22 = c.key.map(b.today_in_person).fillna(0)
        c["reported_today"] = (c.today26 > 0) | (today22 == 0)
        prev = t22[t22.day == n - 1].set_index("key") if n >= 2 else None
        ev22_prev = c.key.map(prev.cum_ev_total).fillna(0) if prev is not None else c.key.map(b.cum_by_mail).fillna(0)
        c["ev22"] = np.where(c.reported_today, c.key.map(b.cum_ev_total).fillna(0), ev22_prev)
        c["today22"] = today22
        mail_prev = c.key.map(prev.cum_by_mail).fillna(0) if prev is not None else c.key.map(b.cum_by_mail).fillna(0)
        c["mail22"] = np.where(c.reported_today, c.key.map(b.cum_by_mail).fillna(0), mail_prev)
    # 2018, same point (30 largest counties only)
    t18 = load_2018()
    c["ev18"], c["reg18_ev"] = np.nan, np.nan
    if t18:
        d18 = t18.get(base_day, {}); d18p = t18.get(n - 1, {}) if n >= 2 else {}
        for j, k in zip(c.index, c.key):
            if k not in d18:
                continue
            if n == 0:
                v = d18[k]["cum_mail"]
            elif c.reported_today[j]:
                v = d18[k]["cum_total"]
            else:
                v = d18p[k]["cum_total"] if k in d18p else d18[k]["cum_mail"]
            c.loc[j, "ev18"], c.loc[j, "reg18_ev"] = v, d18[k]["reg"]
    c["at_2018_pace"] = c.ev18 / c.reg18_ev * c.reg26
    c["pace18"] = c.ev26 / c.at_2018_pace
    c["ev22_final"] = c.key.map(final22.cum_ev_total).fillna(0)
    c["ev18_final"] = c.key.map(b.ev_2018).fillna(0)
    c["pct26"] = c.ev26 / c.reg26
    c["pct22"] = np.where(c.reg22 > 0, c.ev22 / c.reg22, 0)
    c["at_2022_pace"] = c.pct22 * c.reg26
    c["pace"] = np.where(c.at_2022_pace > 0, c.ev26 / c.at_2022_pace, np.nan)
    # a big county with no ballots while 2022 had plenty has almost surely not reported yet
    c["missing"] = (c.ev26 == 0) & (c.at_2022_pace > 300) | ((c.at_2022_pace > 2000) & (c.pace < 0.05))
    # Once in-person voting has started, a county whose state file has almost no in-person votes (Harris
    # with 4 on day 1, when the county itself reported 70,000+) has not uploaded yet. Treat it as not posted
    # rather than show a falsely low share of 2022. Same for mail (Bexar: 10 mail ballots on day 1).
    if n >= 1:
        in22 = (c.ev22 - c.mail22) * np.where(c.reg22 > 0, c.reg26 / c.reg22.where(c.reg22 > 0, 1), 1)
        mail22 = c.mail22 * np.where(c.reg22 > 0, c.reg26 / c.reg22.where(c.reg22 > 0, 1), 1)
        # 50%: partial uploads have shown up at 30-45% of 2022 (El Paso, Collin, Fort Bend on day 2) while every
        # complete county is running near or above 2022
        c["missing"] = c.missing | ((in22 > 500) & (c.in26 < 0.5 * in22)) | ((mail22 > 500) & (c.mail26 < 0.5 * mail22))

    # partisan read of the ballots cast so far
    s = c[share_col].values
    ms = np.array([mail_skew.get(x, mail_default) for x in c.county])
    s_mail, s_in = np.clip(s + ms, .02, .98), np.clip(s + ev_skew, .02, .98)
    c["est_T"] = c.mail26 * s_mail + c.in26 * s_in
    c["est_net"] = 2 * c.est_T - c.ev26                                   # Democrat minus Republican
    # the same number of ballots, spread across counties the way 2022 was at this point
    rep = ~c.missing
    tot_rep = c.ev26[rep].sum()
    w22 = np.where(rep, c.at_2022_pace, 0)
    mix22 = w22 / w22.sum() * tot_rep if w22.sum() > 0 else w22
    mail_frac22 = np.where(c.ev26 > 0, c.mail26 / c.ev26.replace(0, 1), 1.0 if n == 0 else 0.1)
    est_T22 = mix22 * (mail_frac22 * s_mail + (1 - mail_frac22) * s_in)
    share_now = c.est_T[rep].sum() / max(tot_rep, 1)
    share_22mix = est_T22.sum() / max(mix22.sum(), 1)
    mix_effect_pts = (share_now - share_22mix) * 200                        # margin points
    mix_effect_votes = (share_now - share_22mix) * 2 * tot_rep

    # turnout projection: if each county keeps its pace vs 2022, final 2026 votes ~ pace x 2022 final votes
    proj = None
    if n >= 2:
        final_22_votes = c.gov22_total.astype(float)
        pace = c.pace.where(rep & c.pace.notna(), 1.0).clip(0.4, 2.0)
        proj = float((pace * final_22_votes * (c.reg26 / c.reg22.replace(0, np.nan)).fillna(1)).sum())

    def region_rows():
        out = []
        for r in REGIONS:
            m = (c.region == r) & rep
            ev, exp22 = c.ev26[m].sum(), c.at_2022_pace[m].sum()
            out.append(dict(name=r, ev=int(ev), at_2022_pace=int(exp22), pace=float(ev / exp22) if exp22 else None,
                            est_margin=float(c.est_net[m].sum() / ev * 100) if ev else None,
                            share_of_ev=float(ev / max(tot_rep, 1))))
        return out

    # statewide day-by-day series (cumulative % of registered voters)
    s22 = t22.groupby("day").agg(ev=("cum_ev_total", "sum"), reg=("reg_voters", "sum"))
    series22 = [dict(day=int(k), pct=float(v.ev / v.reg)) for k, v in s22.iterrows()]
    series26 = []
    for dstr in dates:
        dd = datetime.strptime(dstr, "%m/%d/%Y").date()
        tot = sum(v[0] + v[1] for v in daily[dstr]["counties"].values())
        series26.append(dict(day=day_number(dd), date=dd.isoformat(), pct=float(tot / c.reg26.sum()), ballots=int(tot)))

    top = c.ev18.notna() & rep
    pace18_top = float(c.ev26[top].sum() / c.at_2018_pace[top].sum()) if top.any() else None
    today = None
    if n >= 1:
        rt = (c.today26 > 0) & rep
        t22_adj = (c.today22 * c.reg26 / c.reg22.replace(0, np.nan)).fillna(0)
        today = dict(in_person=int(c.today26.sum()), counties=int((c.today26 > 0).sum()),
                     vs22=float(c.today26[rt].sum() / t22_adj[rt].sum()) if rt.any() and t22_adj[rt].sum() > 0 else None,
                     raw22=int(c.today22[rt].sum()), adj22=int(t22_adj[rt].sum()))

    keys30 = set(t18.get(1, {}).keys()) if t18 else set()
    in30 = c.key.isin(keys30)
    series_top = dict(y2018=[dict(day=dd, pct=sum(v["cum_total"] for v in t18[dd].values()) / sum(v["reg"] for v in t18[dd].values()))
                             for dd in sorted(t18)] if t18 else [],
                      y2022=[dict(day=int(dd), pct=float(g[g.key.isin(keys30)].cum_ev_total.sum() / g[g.key.isin(keys30)].reg_voters.sum()))
                             for dd, g in t22.groupby("day")],
                      y2026=[dict(day=day_number(datetime.strptime(ds, "%m/%d/%Y").date()),
                                  pct=float(sum(v[0] + v[1] for k, v in daily[ds]["counties"].items() if k in set(c.county[in30]))
                                            / c.reg26[in30].sum())) for ds in dates] if in30.any() else [])

    counties = {}
    for _, r in c.iterrows():
        counties[r.county] = dict(ev=int(r.ev26), mail=int(r.mail26), in_person=int(r.in26), ev22=int(round(r.at_2022_pace)),
                                  ev22_raw=int(r.ev22), today=int(r.today26), reported_today=bool(r.reported_today), live=bool(r.live),
                                  today22=int(r.today22) if "today22" in c and not pd.isna(r.today22) else None,
                                  mail22=int(r.mail22),
                                  ev18=None if pd.isna(r.at_2018_pace) else int(round(r.at_2018_pace)),
                                  ev18_raw=None if pd.isna(r.ev18) else int(r.ev18),
                                  pace18=None if pd.isna(r.pace18) or r.missing else round(float(r.pace18), 3),
                                  pace=None if pd.isna(r.pace) else round(float(r.pace), 3), missing=bool(r.missing), report=bool(r.report),
                                  est_net=int(round(r.est_net)), pct=round(float(r.pct26) * 100, 2),
                                  pct22=round(float(r.pct22) * 100, 2))
    out = dict(
        as_of=latest, updated=daily[latest].get("updated"), day=n, mail_only=bool(c.in26.sum() == 0),
        total=int(c.ev26.sum()), mail=int(c.mail26.sum()), in_person=int(c.in26.sum()),
        at_2022_pace=int(c.at_2022_pace.sum()), pace=float(c.ev26[rep].sum() / max(c.at_2022_pace[rep].sum(), 1)),
        reg=int(c.reg26.sum()), est_share=float(share_now), est_margin=float((2 * share_now - 1) * 100),
        mix_effect_pts=float(mix_effect_pts), mix_effect_votes=int(round(mix_effect_votes)),
        projected_turnout=proj, final_2022_votes=int(c.gov22_total.sum()), final_2018_votes=int(c.sen18_total.sum()),
        ev_2022_final=int(c.ev22_final.sum()), ev_2018_final=int(c.ev18_final.sum()),
        missing=[x for x in c.sort_values("exp_votes", ascending=False).county[c.missing]][:12],
        regions=region_rows(), series22=series22, series26=series26, series_top=series_top, counties=counties,
        today=today, pace18_top=pace18_top, n_top=int(in30.sum()), live_counties=[x for x in c.county[c.live]],
        state_in_person=int((c.in26 - np.where(c.live, c.today26, 0)).sum()),     # official state numbers only
    )
    out["groups"] = turnout_groups(c)
    out["turnout_effect"] = turnout_effect(c, share_col)
    out["primary"] = primary_mix(c)
    out["story"] = story(out, c, names)
    return out


def story(e, c, names=("Talarico", "Paxton")):
    """Plain-language read of the early vote, generated from the numbers."""
    L = []
    fmt = lambda v: f"{v:,.0f}"
    D, R = names
    lead = lambda m: (D if m >= 0 else R) + f" +{abs(m):.1f}"
    big = c[~c.missing & (c.exp_votes > 150000)].copy()
    if e["day"] == 0:
        # before in-person voting only mail exists and many counties have not posted: stick to plain facts
        h = e["counties"].get("Harris", {})
        L.append(f"<strong>In-person early voting starts Monday, Oct. 19.</strong> So far only mail ballots are in: "
                 f"{fmt(e['mail'])} statewide, from voters 65 and older, voters with disabilities and a few others.")
        if h.get("ev"):
            L.append(f"<strong>Harris County has {fmt(h['ev'])} mail ballots back.</strong> In 2022 it had about "
                     f"{fmt(h['ev22'])} (adjusted for registration growth) by the end of the first day of early voting, so it is at "
                     f"{h['ev'] / max(h['ev22'], 1) * 100:.0f}% of that level with a day of mail still to come.")
        if e["missing"]:
            L.append(f"<strong>Many counties have not posted mail counts yet,</strong> including {', '.join(e['missing'][:6])}. "
                     f"The statewide total will jump when they do, so it is too early to compare Texas as a whole with past years.")
        L.append("<strong>Starting Monday, this page compares every county's turnout with the same day in 2022</strong> "
                 "and estimates whom the mix of voters favors.")
        L.append("Turnout shows where votes come from, not whom they are for.")
        return L
    else:
        L.append(f"<strong>Day {e['day']} of 12: {fmt(e['total'])} Texans have voted early</strong> "
                 f"({fmt(e['in_person'])} in person, {fmt(e['mail'])} by mail), {e['total']/e['reg']*100:.1f}% of registered voters.")
        L.append(f"<strong>Turnout is {'ahead of' if e['pace'] >= 1 else 'behind'} 2022's pace:</strong> "
                 f"{abs(e['pace']-1)*100:.0f}% {'more' if e['pace'] >= 1 else 'fewer'} ballots than on the same day in 2022, after adjusting for registration growth.")
        if e["projected_turnout"]:
            L.append(f"<strong>At this pace, about {e['projected_turnout']/1e6:.1f} million Texans will vote</strong> "
                     f"(2022: {e['final_2022_votes']/1e6:.1f} million; 2018: {e['final_2018_votes']/1e6:.1f} million).")
    if e.get("today") and e["today"]["counties"] < 254:
        t = e["today"]
        L.append(f"<strong>Today so far:</strong> {fmt(t['in_person'])} in-person votes from {t['counties']} of 254 counties. "
                 + (f"In those counties that is {abs(t['vs22'] - 1) * 100:.0f}% {'more' if t['vs22'] >= 1 else 'fewer'} than the same day in 2022 "
                    f"({fmt(t['in_person'])} vs. {fmt(t['adj22'])}, adjusted for registration). " if t["vs22"] else "")
                 + "Counties that have not posted today are compared with 2022 through yesterday.")
    if e.get("pace18_top"):
        L.append(f"<strong>Against 2018,</strong> the last high-turnout midterm, the 30 largest counties are "
                 f"{abs(e['pace18_top'] - 1) * 100:.0f}% {'ahead of' if e['pace18_top'] >= 1 else 'behind'} the same day.")
    if len(big):
        up = big.sort_values("pace", ascending=False).head(3)
        down = big.sort_values("pace").head(3)
        pf = lambda r: f"{r.county} ({(r.pace-1)*100:+.0f}%)"
        L.append(f"<strong>Strongest turnout vs. 2022:</strong> {', '.join(pf(r) for _, r in up.iterrows())}. "
                 f"<strong>Weakest:</strong> {', '.join(pf(r) for _, r in down.iterrows())}.")
    regs = {r["name"]: r for r in e["regions"]}
    u, rural = regs["Urban core"], regs["Rural"]
    if u["pace"] and rural["pace"]:
        better = "Democrats" if u["pace"] > rural["pace"] else "Republicans"
        L.append(f"<strong>The four big blue counties are at {u['pace']*100:.0f}% of their 2022 pace; rural Texas is at {rural['pace']*100:.0f}%.</strong> "
                 f"That gap favors {better}.")
    L.append(f"<strong>What it means:</strong> if each county's ballots split the way the county is expected to vote "
             f"(with mail leaning Democratic), the early vote so far is about <strong>{lead(e['est_margin'])}</strong>. "
             f"Spread across counties the way 2022 was, the same ballots would be about {lead(e['est_margin'] - e['mix_effect_pts'])}, "
             f"so this year's mix is {abs(e['mix_effect_pts']):.1f} points {'better for ' + D if e['mix_effect_pts'] >= 0 else 'better for ' + R} "
             f"(roughly {fmt(abs(e['mix_effect_votes']))} net votes).")
    if e["missing"]:
        L.append(f"<strong>Not reported yet:</strong> {', '.join(e['missing'][:6])}{' and others' if len(e['missing']) > 6 else ''}. "
                 f"These are left out of the comparisons until they post numbers.")
    L.append("Early votes lean Democratic in Texas cities and mail ballots lean Democratic in Harris, so an early Democratic lead is expected "
             "and shrinks once Election Day votes are added. Turnout shows where votes come from, not whom they are for.")
    return L

"""Late-count projections for close races still counting after Nov. 3 (Mississippi Senate, Alaska Senate and governor).
Writes data/late_count.json. If NBC cannot be reached, the last good file is kept.

How a race is projected:
  1. Counted votes by county (Mississippi) or state House district (Alaska), from NBC News / AP results pages.
  2. Votes left in each place = counted / share of expected vote in - counted.
  3. How the votes left lean: the place's own count so far, blended (by share counted) with its 2024 result shifted
     by the swing every reporting place shows since 2024 (Mississippi; Alaska's 2024 results use different names
     for its districts, so it uses its own count only), then moved toward how ballots counted late have voted:
     Alaska counts mail and early ballots for days after Election Day, and those lean differently.
  4. 20,000 runs: a shared statewide error, a place-by-place error and a turnout error on the votes left.
  5. Ranked choice (Alaska): if no one passes 50%, the last-place candidate is dropped and their voters' next
     choices move (same-party candidates first; some ballots stop counting). Transfer rates vary run to run.
"""
import json, os, random, re, sys, time, urllib.request
from datetime import datetime, timezone

OUT = "data/late_count.json"
N = 20000
UA = {"User-Agent": "Mozilla/5.0 (texas-forecast late-count)"}

RACES = [
    # key, state, NBC page, 2024 baseline page (None: no baseline), ranked choice,
    # late: how much of the mail/early lean the votes left carry. Alaska: late counts moved 2024 results by 1 to 4
    #   points (Ballot Measure 2 led on election night and lost); 0.25-1.0 of the lean spans that.
    # left_sd: uncertainty in how many ballots are left.
    # counts: share of the ballots left that end up counted. Mississippi's are largely affidavit (provisional)
    #   ballots, many of which are rejected; the state reported no 2024 affidavit or mail totals to the federal
    #   election survey (EAVS) and keeps no statewide count, so the range is wide.
    dict(key="ms_senate", state="Mississippi", office="U.S. Senate", page="mississippi-senate-results",
         base="mississippi-president-results", rcv=False, late=(0.0, 0.5), left_sd=0.25, counts=(0.35, 1.0), unit="county"),
    dict(key="ak_senate", state="Alaska", office="U.S. Senate", page="alaska-senate-results",
         base=None, rcv=True, late=(0.25, 1.0), left_sd=0.15, counts=(0.9, 1.0), unit="district"),
    dict(key="ak_governor", state="Alaska", office="Governor", page="alaska-governor-results",
         base=None, rcv=True, late=(0.25, 1.0), left_sd=0.15, counts=(0.9, 1.0), unit="district"),
]
PARTY = {"dem": "D", "gop": "R"}


def fetch(page, year=2026, tries=3):
    url = f"https://www.nbcnews.com/politics/{year}-elections/{page}"
    for i in range(tries):
        try:
            s = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode()
            return json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', s, re.S).group(1))["props"]["pageProps"]
        except Exception as e:
            err = e; time.sleep(3 * (i + 1))
    raise RuntimeError(f"{page}: {err}")


def key(n):
    return re.sub(r"[^a-z0-9]", "", n.lower())


def num(v):
    return int(str(v).replace(",", "")) if v not in (None, "") else 0


def parse(pp):
    """-> candidates [{name, party}], areas [{name, votes{name: n}, total, pin}], modes {type: {name: n}}"""
    race = pp["races"][0]
    cands, seen = [], set()
    areas = []
    for a in race["areas"]:
        v = {}
        for c in a["candidates"]:
            nm = c["lastName"]
            if "write-in" in nm.lower():
                nm = "Write-ins"
            v[nm] = v.get(nm, 0) + c["votes"]
            if nm not in seen:
                seen.add(nm)
                p = c["party"] if nm != "Write-ins" else "other"
                cands.append({"name": nm, "full": c.get("name", nm) if nm != "Write-ins" else "Write-ins", "party": PARTY.get(p, "I")})
        areas.append({"name": a["name"], "votes": v, "total": a["votes"], "pin": a["percentIn"] / 100})
    modes = {}
    for vm in pp.get("voteModes") or []:
        for m in vm.get("modes", []):
            modes[m["typeOfVote"]] = {("Write-ins" if "write-in" in c["lastName"].lower() else c["lastName"]): num(c["votes"]) for c in m["candidates"]}
    tot = {c["name"]: sum(a["votes"].get(c["name"], 0) for a in areas) for c in cands}
    cands.sort(key=lambda c: -tot[c["name"]])
    return cands, areas, modes, pp.get("currentTime")


def baseline(page):
    pp = fetch(page, 2024)
    out = {}
    for a in pp["races"][0]["areas"]:
        d = sum(c["votes"] for c in a["candidates"] if c["party"] == "dem")
        r = sum(c["votes"] for c in a["candidates"] if c["party"] == "gop")
        out[key(a["name"])] = {"total": a["votes"], "m": (d - r) / max(d + r, 1)}
    return out


def shares(v):
    t = sum(v.values()) or 1
    return {k: x / t for k, x in v.items()}


def rcv(tot, cands, rng):
    """Round-by-round count. tot: {name: votes}. Returns (winner, final two {name: votes}, rounds)."""
    party = {c["name"]: c["party"] for c in cands}
    live = {k: v for k, v in tot.items() if v > 0}
    rounds = []
    while True:
        s = sum(live.values())
        lead = max(live, key=live.get)
        rounds.append(dict(live))
        if live[lead] > s / 2 or len(live) <= 2:
            return lead, dict(live), rounds
        out = min(live, key=live.get)
        n = live.pop(out)
        p = party.get(out, "I")
        same = {k: v for k, v in live.items() if party.get(k) == p and p in "DR"}
        other = {k: v for k, v in live.items() if k not in same}
        if out == "Write-ins":
            to_same, to_other = 0.0, rng.uniform(0.3, 0.6)
        elif same:
            # Alaska's Aug. 2022 House tally: Begich (R) voters went 50% Palin (R), 29% Peltola (D), 21% no next choice
            to_same, to_other = rng.uniform(0.45, 0.75), rng.uniform(0.1, 0.3)
        else:   # independents and minor parties: split, many stop
            to_same, to_other = 0.0, rng.uniform(0.45, 0.8)
        for grp, frac in ((same, to_same), (other, to_other)):
            gs = sum(grp.values())
            if not gs:
                continue
            if grp is other and p == "I":
                # a lone independent's voters: lean a random amount toward one side
                tilt = rng.uniform(-0.25, 0.25)
                w = {k: (0.5 + (tilt if party.get(k) == "D" else -tilt)) for k in grp}
                ws = sum(w.values())
                for k in grp:
                    live[k] += n * frac * w[k] / ws
            else:
                for k in grp:
                    live[k] += n * frac * grp[k] / gs


def rating(p_d, margin):
    """Race rating from the Democrat's chance and the projected margin (points, + = D).
    Within 1 point the race is never more than Lean: the count of rejected and late ballots alone can move that much."""
    side = "Democratic" if p_d >= 0.5 else "Republican"
    p = max(p_d, 1 - p_d)
    if p < 0.65:
        return "Toss-up"
    level = "Safe" if p >= 0.97 else "Likely" if p >= 0.85 else "Lean"
    if abs(margin) < 1 and level != "Lean":
        level = "Lean"
    return f"{level} {side}"


def project(cfg, rng):
    pp = fetch(cfg["page"])
    cands, areas, modes, t = parse(pp)
    names = [c["name"] for c in cands]
    party = {c["name"]: c["party"] for c in cands}
    D = next((c["name"] for c in cands if c["party"] == "D"), None)
    R = next((c["name"] for c in cands if c["party"] == "R"), None)
    counted = {n: sum(a["votes"].get(n, 0) for a in areas) for n in names}
    T = sum(counted.values())
    exp_total = sum(a["total"] / a["pin"] for a in areas if a["pin"] > 0)
    overall = shares(counted)

    # late-ballot lean: mail + early ballots vs. everything counted
    late = {}
    for m, v in modes.items():
        if m != "Election Day":
            for k, x in v.items():
                late[k] = late.get(k, 0) + x
    late_shift = {}
    if sum(late.values()) > 1000:
        ls = shares(late)
        late_shift = {n: ls.get(n, 0) - overall.get(n, 0) for n in names}

    B = baseline(cfg["base"]) if cfg["base"] else {}
    rep = [a for a in areas if a["pin"] > 0 and key(a["name"]) in B and a["votes"].get(D, 0) + a["votes"].get(R, 0) > 0]
    swing = 0.0
    if rep:
        w = sum(a["total"] for a in rep)
        swing = sum(a["total"] * ((a["votes"].get(D, 0) - a["votes"].get(R, 0)) / (a["votes"].get(D, 0) + a["votes"].get(R, 0)) - B[key(a["name"])]["m"]) for a in rep) / w
    ratio = (sum(a["total"] / a["pin"] for a in rep) / sum(B[key(a["name"])]["total"] for a in rep)) if rep else 1.0

    plan, table = [], []
    for a in areas:
        if a["pin"] > 0:
            left = a["total"] / a["pin"] - a["total"]
        elif key(a["name"]) in B:
            left = B[key(a["name"])]["total"] * ratio
        else:
            continue
        if left < 1:
            continue
        s = shares(a["votes"]) if a["total"] else dict(overall)
        b = B.get(key(a["name"]))
        if b and D and R:
            dr = s.get(D, 0) + s.get(R, 0) or 0.97
            obs = (s.get(D, 0) - s.get(R, 0)) / dr if a["total"] else b["m"] + swing
            mu = a["pin"] * obs + (1 - a["pin"]) * (b["m"] + swing)
            s = dict(s); s[D], s[R] = dr * (1 + mu) / 2, dr * (1 - mu) / 2
        plan.append((left, s))
        cm = (a["votes"].get(D, 0) - a["votes"].get(R, 0)) / max(a["total"], 1) * 100
        table.append({"name": a["name"], "left": round(left), "pin": round(a["pin"] * 100, 1),
                      "counted_margin": round(cm, 1), "counted": a["total"]})
    # county "% in" figures are rounded; scale the votes left so the total matches NBC/AP's statewide share counted
    state_in = (pp["races"][0].get("summary") or {}).get("percentIn")
    state_in = float(state_in) / 100 if state_in not in (None, "") and 0 < float(state_in) <= 100 else None
    raw_left = sum(p[0] for p in plan)
    if state_in and raw_left > 0:
        k = (T / state_in - T) / raw_left
        plan = [(left * k, s) for left, s in plan]
        for row in table:
            row["left"] = round(row["left"] * k)
    table.sort(key=lambda r: -r["left"])
    left_total = sum(p[0] for p in plan)

    wins = {n: 0 for n in names}
    margins, first, rcv_runs = [], {n: [] for n in names}, 0
    for _ in range(N):
        g = rng.gauss(0, 0.05)                  # shared error on D vs. R share of the votes left
        tshift = max(rng.gauss(0, cfg["left_sd"]), -0.9)   # how many votes are really left
        tshift = (1 + tshift) * rng.uniform(*cfg["counts"]) - 1   # and how many of those are accepted
        lw = rng.uniform(*cfg["late"])
        tot = dict(counted)
        for left, s in plan:
            loc = rng.gauss(0, 0.03)
            v = {n: max(s.get(n, 0) + lw * late_shift.get(n, 0), 0) for n in names}
            if D: v[D] = max(v[D] + (g + loc) / 2, 0)
            if R: v[R] = max(v[R] - (g + loc) / 2, 0)
            vs = sum(v.values()) or 1
            for n in names:
                tot[n] += left * (1 + tshift) * v[n] / vs
        ts = sum(tot.values())
        for n in names:
            first[n].append(tot[n] / ts * 100)
        if cfg["rcv"]:
            win, fin, rounds = rcv(tot, cands, rng)
            rcv_runs += len(rounds) > 1
        else:
            win = max(tot, key=tot.get); fin = tot
        wins[win] += 1
        if D and R and D in fin and R in fin:
            margins.append((fin[D] - fin[R]) / (fin[D] + fin[R]) * 100)
        else:   # final two are not one D and one R: report the winner's lead over the runner-up
            a, b = sorted(fin.values(), reverse=True)[:2]
            margins.append((a - b) / (a + b) * 100 * (1 if party.get(win) == "D" else -1))
    margins.sort()
    pct = lambda xs, q: sorted(xs)[int(q * (len(xs) - 1))]
    return {
        "key": cfg["key"], "state": cfg["state"], "office": cfg["office"], "rcv": cfg["rcv"], "unit": cfg["unit"],
        "source_time": t, "candidates": cands, "dem": D, "rep": R,
        "counted": counted, "counted_total": T, "share_in": state_in or (round(T / exp_total, 3) if exp_total else None),
        "left_total": round(left_total), "swing_vs_2024": round(swing * 100, 1) if rep else None,
        "late_lean": {n: round(x * 100, 1) for n, x in late_shift.items()} if late_shift else None,
        "late_counted": sum(late.values()),
        "win": {n: round(w / N, 4) for n, w in wins.items()},
        "rating": rating(wins.get(D, 0) / N if D else 0, margins[N // 2]),
        "first_round": {n: {"mid": round(pct(first[n], .5), 2), "lo": round(pct(first[n], .05), 2), "hi": round(pct(first[n], .95), 2)} for n in names},
        "rcv_share": round(rcv_runs / N, 3) if cfg["rcv"] else None,
        "margin": {"mid": round(margins[N // 2], 2), "lo": round(margins[N // 20], 2), "hi": round(margins[-N // 20], 2)},
        "places": table[:12],
    }


def main():
    rng = random.Random(20261103)
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {"races": {}}
    races, errors = dict(prev.get("races", {})), []
    for cfg in RACES:
        try:
            races[cfg["key"]] = project(cfg, rng)
            r = races[cfg["key"]]
            top = max(r["win"], key=r["win"].get)
            print(f"{cfg['key']}: {r['rating']}; {r['counted_total']:,} counted (~{r['share_in']:.0%}), {r['left_total']:,} left; "
                  f"{top} {r['win'][top]:.1%}, margin {r['margin']['mid']:+.2f} ({r['margin']['lo']:+.2f} to {r['margin']['hi']:+.2f})")
        except Exception as e:
            errors.append(f"{cfg['key']}: {e}")
            print(f"{cfg['key']}: FAILED ({e}); keeping last good projection", file=sys.stderr)
    if not races:
        sys.exit(1)
    json.dump({"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00"), "races": races, "errors": errors},
              open(OUT, "w"), indent=1)


if __name__ == "__main__":
    main()

"""Sanity checks between the last published run and this one. Tests catch broken code; these catch
bad data that still looks valid (a garbled poll table, a feed glitch that shrinks a county's count).

If any check fails the script exits 1 and nothing is published; the site keeps its last good version.
Set SANITY_OVERRIDE=1 to publish anyway (the GitHub "Run workflow" button has a checkbox for it).
On success, data/last_published.json is updated for the next comparison.
Run from project root after export.py:  PYTHONPATH=pipeline python3 pipeline/sanity.py
"""
import json, os, sys
sys.path.insert(0, "pipeline")
from races import RACES

SNAP = "data/last_published.json"
LIMITS = dict(
    poll_avg_pts=3.0,         # statewide poll-average margin may not jump more than this between runs
    poll_count_drop=0.25,     # parsed poll count may not fall by more than 25%
    market_lo=0.01, market_hi=0.99,
    early_drop=0.02,          # early-vote total may not fall by more than 2%
    early_county_drop=0.01,   # a county's early-vote total may not fall at all (1% and 200 votes of slack)
    county_drop=0.05,         # a county's counted votes may not fall by more than 5% (and 500 votes)
    counted_over=1.25,        # counted votes may not exceed 125% of expected turnout
    needle_pts=0.25,          # with no votes counted, the win chance may not move more than 25 points
)


def snapshot():
    snap = {}
    for key in RACES:
        d = json.load(open(f"site/data_{key}.json"))
        n_polls = sum(1 for _ in open(f"data/polls_{key}.csv")) - 1
        counted = {c["name"]: c["counted"]["d"] + c["counted"]["r"] for c in d["counties"] if c.get("counted")}
        snap[key] = dict(generated=d["generated"], mode=d["mode"], poll_avg=(2 * d["polls"]["average"] - 1) * 100,
                         n_polls=n_polls, markets={m["source"]: m["d"] for m in d["markets"]}, needle=d["needle"]["p"],
                         early_total=(d.get("early") or {}).get("total", 0), counted=counted,
                         early_counties={n: x["ev"] for n, x in ((d.get("early") or {}).get("counties") or {}).items()
                                         if not x.get("missing")},
                         expected_turnout=d["forecast"]["turnout"])
    return snap


def check(prev, cur):
    problems = []
    for key, c in cur.items():
        name = RACES[key]["office"]
        for src, v in c["markets"].items():
            if not LIMITS["market_lo"] < v < LIMITS["market_hi"]:
                problems.append(f"{name}: {src} price {v:.2f} is outside 1-99%")
        tot = sum(c["counted"].values())
        if tot > LIMITS["counted_over"] * c["expected_turnout"]:
            problems.append(f"{name}: {tot:,} counted votes is more than 125% of expected turnout")
        p = (prev or {}).get(key)
        if not p:
            continue
        if abs(c["poll_avg"] - p["poll_avg"]) > LIMITS["poll_avg_pts"]:
            problems.append(f"{name}: poll average jumped {p['poll_avg']:+.1f} -> {c['poll_avg']:+.1f}")
        if c["n_polls"] < (1 - LIMITS["poll_count_drop"]) * p["n_polls"]:
            problems.append(f"{name}: poll count fell {p['n_polls']} -> {c['n_polls']} (poll page may have changed)")
        if p["early_total"] and c["early_total"] < (1 - LIMITS["early_drop"]) * p["early_total"]:
            problems.append(f"{name}: early-vote total fell {p['early_total']:,} -> {c['early_total']:,}")
        for county, v in (p.get("early_counties") or {}).items():
            now = c["early_counties"].get(county)
            if now is not None and v - now > max(200, LIMITS["early_county_drop"] * v):
                problems.append(f"{name}: {county} early votes fell {v:,} -> {now:,} (totals can only go up)")
        for county, v in p["counted"].items():
            now = c["counted"].get(county, 0)
            if v - now > max(500, LIMITS["county_drop"] * v):
                problems.append(f"{name}: {county} counted votes fell {v:,} -> {now:,}")
        if c["mode"] in ("pre", "early") and p["mode"] in ("pre", "early") and abs(c["needle"] - p["needle"]) > LIMITS["needle_pts"]:
            problems.append(f"{name}: win chance moved {p['needle']:.0%} -> {c['needle']:.0%} with no votes counted")
    return problems


def main():
    prev = json.load(open(SNAP)) if os.path.exists(SNAP) else None
    cur = snapshot()
    problems = check(prev, cur)
    override = os.environ.get("SANITY_OVERRIDE") == "1"
    for msg in problems:
        print("SANITY:", msg)
    if problems and not override:
        print(f"SANITY CHECKS FAILED ({len(problems)}) - not publishing. Re-run with the override if the change is real.")
        return 1
    json.dump(cur, open(SNAP, "w"), indent=1)
    print("sanity checks passed" if not problems else "sanity problems overridden - publishing")
    return 0


if __name__ == "__main__":
    sys.exit(main())

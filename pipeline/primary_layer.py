"""Early voters by 2026 primary: how many of this fall's early voters voted early (or by mail) in the March 2026
Democratic or Republican primary.

Source: the Texas Secretary of State's daily lists of who voted early, one file per county per day. They have names,
so nothing per voter is ever written to disk or published: voter IDs live only in memory while this runs, and only
county totals are saved (data/primary_layer.json).

Limits, shown on the site: the state's free system has only the 2026 primaries, and only people who voted early or
by mail in them; people who voted on primary day itself (March 3) count as "no 2026 primary here".
"""
import base64
import csv
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SOS = "https://goelect.txelections.civixapps.com/api-ivis-system/api/v1"
GENERAL, DEM_PRIMARY, REP_PRIMARY = 53815, 53814, 53813
WORKERS = 8


def get_json(url, tries=4):
    for i in range(tries):
        try:
            raw = urlopen(Request(url, headers={"User-Agent": "texas-forecast"}), timeout=90).read()
            return json.loads(raw) if raw.strip() else None
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def elections():
    d = get_json(f"{SOS}/getFile?type=EVR_ELECTION")
    return {e["id"]: e for e in json.loads(base64.b64decode(d["upload"]))["elections"]}


def voter_ids(election_id, date, county, county_id):
    """Set of voter IDs on one county's list for one day (empty if the county has not posted)."""
    q = urlencode(dict(type="EVR_EARLYVOTING", electionId=election_id, electionDate=date, county=county,
                       countyId=county_id, format="csv"))
    d = get_json(f"{SOS}/getFileByFormat?{q}")
    if not d or not d.get("upload"):
        return set()
    rows = list(csv.reader(io.StringIO(base64.b64decode(d["upload"]).decode("utf-8", "ignore"))))
    if not rows:
        return set()
    head = [h.strip().upper() for h in rows[0]]
    col = next((k for k, h in enumerate(head) if h in ("ID_VOTER", "VUID", "VOTER_ID")), None)
    if col is None:
        print(f"  unexpected columns for {county} {date}: {head[:6]}", file=sys.stderr)
        return set()
    return {r[col].strip() for r in rows[1:] if len(r) > col and r[col].strip()}


def collect(election, dates, counties):
    """{county_name: set of voter IDs} over the given days."""
    jobs = [(c["name"], c["county_id"], d) for c in counties for d in dates]
    out = {c["name"]: set() for c in counties}
    with ThreadPoolExecutor(WORKERS) as ex:
        for (name, _, _), ids in zip(jobs, ex.map(lambda j: voter_ids(election, j[2], j[0], j[1]), jobs)):
            out[name] |= ids
    return out


def title(name):
    from fetch import NAME_FIX
    t = name.title()
    return NAME_FIX.get(t, t)


def main(limit=None):
    E = elections()
    gen = E[GENERAL]
    counties = gen["counties"][:limit] if limit else gen["counties"]
    today = datetime.now(timezone.utc).date()
    gen_dates = [d["date"] for d in gen["early_voting_dates"] if datetime.strptime(d["date"], "%m/%d/%Y").date() <= today]
    t0 = time.time()
    voted = collect(GENERAL, gen_dates, counties)
    dem = collect(DEM_PRIMARY, [d["date"] for d in E[DEM_PRIMARY]["early_voting_dates"]], counties)
    rep = collect(REP_PRIMARY, [d["date"] for d in E[REP_PRIMARY]["early_voting_dates"]], counties)
    # A voter can vote early in one county's primary and move; match statewide, not just within the county.
    all_dem = set().union(*dem.values())
    all_rep = set().union(*rep.values())
    del dem, rep
    rows = {}
    for c in counties:
        v = voted[c["name"]]
        d, r = v & all_dem, v & all_rep
        both = len(d & r)
        rows[title(c["name"])] = dict(voters=len(v), dem=len(d) - both, rep=len(r) - both, both=both,
                                      none=len(v) - len(d | r))
    tot = {k: sum(x[k] for x in rows.values()) for k in ("voters", "dem", "rep", "both", "none")}
    out = dict(fetched=datetime.now(timezone.utc).isoformat(timespec="seconds"), through=gen_dates[-1] if gen_dates else None,
               primary_early_voters=dict(dem=len(all_dem), rep=len(all_rep)), total=tot, counties=rows)
    if not limit:
        json.dump(out, open("data/primary_layer.json", "w"), separators=(",", ":"))
    print(f"primary layer: {tot['voters']:,} early voters through {out['through']}, {time.time() - t0:.0f}s; "
          f"D-primary {tot['dem']:,} R-primary {tot['rep']:,} both {tot['both']:,} none {tot['none']:,}")
    return out


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)

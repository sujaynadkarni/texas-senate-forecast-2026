"""Which key counties are behind: missing yesterday's full day (or not shown at all) after noon Central, when the
state's file and the county reports should normally have it. Doesn't block publishing; the workflow opens an alert
issue naming them, so a gap gets found and fixed instead of quietly shown. Writes data/lag.json.
Run from project root after export.py:  PYTHONPATH=pipeline python3 pipeline/lag_check.py
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo


def behind(L, now):
    day = L["day"]
    if not day or now.hour < 12:
        return []
    out = []
    for x in L.get("sources", []):
        if x["name"] == "Rural Texas":
            continue
        if not x["shown"]:
            out.append(f"{x['name']}: not shown ({x.get('note') or 'no numbers'}); source: {x['source']}")
        elif x["through_day"] is not None and x["through_day"] < day - 1:
            out.append(f"{x['name']}: through day {x['through_day']} of {day}; source: {x['source']}")
    return out


def broken_sources():
    """County sources that failed this run (a changed PDF, a blocked site): the site falls back to the state's
    numbers for them, so say so."""
    out = []
    for path in ("data/county_reports.json", "data/live.json"):
        try:
            d = json.load(open(path))
        except (OSError, ValueError):
            continue
        for name, rec in (d.get("counties") or {}).items():
            if rec.get("error"):
                out.append(f"{name}: county source failed ({rec['error'][:160]})")
    return out


def held_counties():
    """Counties kept at their last published numbers because new numbers came in lower (a glitch somewhere)."""
    try:
        E = json.load(open("site/data_senate.json"))["early"]["counties"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [f"{n}: kept at last published numbers ({x['held']})" for n, x in E.items() if x.get("held")]


def main():
    L = json.load(open("site/data_senate.json")).get("live_turnout") or {}
    lag = (behind(L, datetime.now(ZoneInfo("America/Chicago"))) if L else []) + broken_sources() + held_counties()
    json.dump(dict(behind=lag), open("data/lag.json", "w"), indent=1)
    for msg in lag:
        print("LAG:", msg)
    print(f"lag check: {len(lag)} key counties behind")


if __name__ == "__main__":
    main()

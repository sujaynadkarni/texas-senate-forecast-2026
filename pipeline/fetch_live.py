"""Same-day ("live") early-vote turnout straight from county websites, before the state compiles it.

Unofficial numbers. Counties covered so far:
  Travis, Montgomery  ElectionLink live tracker: ballots so far + check-ins per hour, with the 2022 and
                      2024 trackers archived for same-day, same-hour comparisons
  Bexar               county early-vote dashboard: ballots per polling place for the latest date
  Dallas              county vote-center map (ArcGIS): today's ballots at each of ~500 vote centers
Writes data/live.json. Past-year trackers never change, so they are cached in data/raw/live_archive_*.json.
"""
import html, json, os, re, subprocess, sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
TX = ZoneInfo("America/Chicago")
EL = "https://updates.electionlink.net/widgets/{slug}/{election}/{page}"
ELECTIONS = {2026: "2026-11-03", 2024: "2024-11-05", 2022: "2022-11-08"}
EV_START = {2026: date(2026, 10, 19), 2024: date(2024, 10, 21), 2022: date(2022, 10, 24)}
ELECTIONLINK = {"Travis": "travistx", "Montgomery": "montgomerytx"}
BEXAR_URL = "https://earlyvotecountsdual.bexar.org"
DALLAS_LAYER = "https://services3.arcgis.com/zqe2kwz79KUqUvxC/arcgis/rest/services/Vote_Center_Finder_view/FeatureServer/4"
DALLAS_MAP = "https://experience.arcgis.com/experience/8204fc2e36cd4fac8729efcedd4fda7f/page/Page?views=Early-Voting"
HOURS = ["7 AM", "8 AM", "9 AM", "10 AM", "11 AM", "12 PM", "1 PM", "2 PM", "3 PM", "4 PM", "5 PM", "6 PM", "7 PM+"]


def get(url):
    out = subprocess.run(["curl", "-sL", "-m", "40", "-A", "Mozilla/5.0 (tx-senate-forecast)", url],
                         capture_output=True, check=True).stdout
    return out.decode("utf-8", "ignore")


def text_of(page):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " | ", t))
    return re.sub(r"(\s*\|\s*)+", " | ", t)


def parse_summary(page):
    """ElectionLink summary page -> ballots cast so far and when the county last refreshed it."""
    t = text_of(page)
    ballots = re.search(r"BALLOTS CAST \| ([\d,]+)", t)
    refreshed = re.search(r"Last Refreshed: \| ([^|]+?) \|", t)
    return dict(ballots=int(ballots.group(1).replace(",", "")) if ballots else None,
                refreshed=refreshed.group(1).strip() if refreshed else None)


def parse_hourly(page):
    """ElectionLink check-ins-per-hour page -> {mm/dd/yyyy: [13 hourly counts, 7 a.m. to close]}"""
    out = {}
    for block in re.findall(r"rows = \[\];(.*?)data\.push\(\{\s*date: '([\d/]+)'", page, flags=re.S):
        body, d = block
        out[d] = [int(v) for _, v in re.findall(r"rows\.push\(\['([^']+)',(\d+)\]\)", body)]
    return out


def parse_bexar(page):
    """Bexar early-vote dashboard -> date shown, ballots that date and to date (summed over polling places)."""
    t = text_of(page)
    d = re.search(r"BALLOTS CAST THIS DATE ([\d/]+)", t)
    rows = re.findall(r"\| ([A-Z][^|]{2,80}?) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+)(?= \|)", t)
    n = lambda s: int(s.replace(",", ""))
    sites = [(name.strip(), n(a), n(b), n(c)) for name, a, b, c in rows]
    return dict(date=d.group(1) if d else None, sites=len(sites), today=sum(s[1] for s in sites),
                to_date=sum(s[3] for s in sites), busiest=sorted(sites, key=lambda s: -s[1])[:3])


def parse_dallas(features, last_edit_ms):
    """Dallas vote-center layer -> today's ballots (C_Daily_Tot) and to date (C_Tot_Vts), summed over centers."""
    num = lambda v: int(float(v)) if v not in (None, "") and str(v).replace(".", "", 1).isdigit() else 0
    rows = [f["attributes"] for f in features]
    refreshed = (datetime.fromtimestamp(last_edit_ms / 1000, TX).strftime("%a %b %-d %-I:%M %p") if last_edit_ms else None)
    return dict(today=sum(num(r.get("C_Daily_Tot")) for r in rows), to_date=sum(num(r.get("C_Tot_Vts")) for r in rows),
                sites=sum(1 for r in rows if num(r.get("C_Daily_Tot")) > 0), refreshed=refreshed,
                busiest=sorted(((r.get("L_Poll_NM"), num(r.get("C_Daily_Tot"))) for r in rows), key=lambda x: -x[1])[:3])


def archive(county, slug, year):
    path = f"data/raw/live_archive_{slug}_{year}.json"
    if os.path.exists(path):
        return json.load(open(path))
    hourly = parse_hourly(get(EL.format(slug=slug, election=ELECTIONS[year], page="CheckinsPerHourGraph.html")))
    if hourly:
        json.dump(hourly, open(path, "w"))
    return hourly


def same_day(year, day_n):
    return (EV_START[year] + timedelta(days=day_n - 1)).strftime("%m/%d/%Y")


def fetch_live():
    today = datetime.now(TX).date()
    day_n = (today - EV_START[2026]).days + 1
    out = {"fetched": NOW, "day": day_n, "date": today.isoformat(), "counties": {}}
    if not 1 <= day_n <= 12:
        out["note"] = "outside early voting"
    for county, slug in ELECTIONLINK.items():
        try:
            summ = parse_summary(get(EL.format(slug=slug, election=ELECTIONS[2026], page="BallotTypeTurnout.html")))
            hourly = parse_hourly(get(EL.format(slug=slug, election=ELECTIONS[2026], page="CheckinsPerHourGraph.html")))
            now_h = hourly.get(today.strftime("%m/%d/%Y"), [])
            hours_in = max([i + 1 for i, v in enumerate(now_h) if v > 0], default=0)
            # compare completed hours only: the hour in progress would understate 2026
            now_tx = datetime.now(TX)
            completed = hours_in if (now_tx.date() != today or now_tx.hour >= 20) else min(hours_in, max(0, now_tx.hour - 7))
            rec = dict(source="county live tracker (ElectionLink)", url=EL.format(slug=slug, election=ELECTIONS[2026], page="index.html"),
                       refreshed=summ["refreshed"], ballots_to_date=summ["ballots"], hourly=now_h, hours_in=hours_in,
                       today=sum(now_h), completed_hours=completed, today_completed=sum(now_h[:completed]),
                       through=(HOURS[completed] if completed < len(HOURS) - 1 else "close") if completed else None, compare={})
            for yr in (2022, 2024):
                past = archive(county, slug, yr).get(same_day(yr, day_n), [])
                if past and sum(past):
                    rec["compare"][str(yr)] = dict(hourly=past, same_hours=sum(past[:completed]), full_day=sum(past))
            out["counties"][county] = rec
        except Exception as e:
            out["counties"][county] = dict(error=f"{type(e).__name__}: {e}")
    try:
        b = parse_bexar(get(BEXAR_URL))
        out["counties"]["Bexar"] = dict(source="county early-vote dashboard", url=BEXAR_URL, date=b["date"], sites=b["sites"],
                                        today=b["today"] if b["date"] == today.strftime("%m/%d/%Y") else 0,
                                        ballots_to_date=b["to_date"], busiest=b["busiest"], hourly=None, compare={})
    except Exception as e:
        out["counties"]["Bexar"] = dict(error=f"{type(e).__name__}: {e}")
    try:
        q = json.loads(get(DALLAS_LAYER + "/query?where=1%3D1&outFields=L_Poll_NM,C_Daily_Tot,C_Tot_Vts&returnGeometry=false&f=json"))
        info = json.loads(get(DALLAS_LAYER + "?f=json"))
        d = parse_dallas(q["features"], (info.get("editingInfo") or {}).get("lastEditDate"))
        out["counties"]["Dallas"] = dict(source="county vote-center map (ArcGIS)", url=DALLAS_MAP, refreshed=d["refreshed"],
                                         today=d["today"], ballots_to_date=d["to_date"], sites=d["sites"], busiest=d["busiest"],
                                         hourly=None, compare={})
    except Exception as e:
        out["counties"]["Dallas"] = dict(error=f"{type(e).__name__}: {e}")
    # Polls open at 7 a.m. Before that, any "today" count is yesterday's still sitting in the county's feed
    # (Dallas showed 61,266 at 6:30 a.m. on Oct. 21, day 2's total), so it must not be counted as today's.
    if datetime.now(TX).hour < 7:
        for rec in out["counties"].values():
            if rec.get("today"):
                rec["today"], rec["note"] = 0, "polls not open yet; count is from the previous day"
    json.dump(out, open("data/live.json", "w"), indent=1)
    # keep each county's highest count for each day: the trackers reset overnight (see early_vote.load_live_days)
    try:
        days = json.load(open("data/live_days.json"))
    except (OSError, ValueError):
        days = {}
    for name, rec in out["counties"].items():
        if rec.get("today") and not rec.get("error"):
            day = days.setdefault(name, {})
            day[out["date"]] = max(day.get(out["date"], 0), int(rec["today"]))
    json.dump(days, open("data/live_days.json", "w"), indent=1, sort_keys=True)
    ok = [k for k, v in out["counties"].items() if "error" not in v]
    return f"{len(ok)} counties: " + ", ".join(f"{k} {out['counties'][k].get('today', 0):,} today" for k in ok)


if __name__ == "__main__":
    print(fetch_live())

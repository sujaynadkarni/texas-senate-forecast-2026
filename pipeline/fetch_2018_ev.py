"""One-time download: Texas SOS 2018 general-election early voting reports (30 largest counties, each day).
Writes data/raw/ev_daily_2018_sos.json  {day: {COUNTYKEY: {reg, today_in, cum_in, cum_mail, cum_total}}}"""
import html, json, re, subprocess
from datetime import date, timedelta

START = date(2018, 10, 22)            # day 1 of early voting, 2018 (12 days, ending Nov. 2)
out = {}
for d in range(12):
    day = START + timedelta(days=d)
    url = f"https://www.sos.texas.gov/elections/earlyvoting/2018/{day.strftime('%b').lower()}{day.day}.shtml"
    raw = subprocess.run(["curl", "-sL", "-m", "40", "-A", "Mozilla/5.0", url], capture_output=True).stdout.decode("utf-8", "ignore")
    t = html.unescape(re.sub(r"<[^>]+>", " | ", raw)); t = re.sub(r"(\s*\|\s*)+", " | ", t)
    seg = t[t.find("Cumulative Percent Early Voting"):]
    n = lambda s: int(s.replace(",", ""))
    rows = re.findall(r"\| ([A-Z][A-Za-z .]+?) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| [\d.]+% \| ([\d,]+) \| [\d.]+% \| ([\d,]+)", seg)
    counties = {re.sub(r"[^A-Z]", "", r[0].upper()): dict(reg=n(r[1]), today_in=n(r[2]), cum_in=n(r[3]), cum_mail=n(r[4]), cum_total=n(r[5]))
                for r in rows if r[0].strip() != "Total"}
    out[str(d + 1)] = counties
    print(d + 1, day, len(counties), "counties", "Harris total", counties.get("HARRIS", {}).get("cum_total"))
json.dump(out, open("data/raw/ev_daily_2018_sos.json", "w"))

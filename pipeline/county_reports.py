"""Official county early-vote reports that come out before the state's file is complete.

  Harris   "Daily Record of Early Voting Check-ins" PDF, updated each evening: in-person check-ins per day and
           mail ballots received (the state's file had Harris at 30,460 in person after day 2; the county, 204,570).
  Denton   daily "Early Voting Totals by Location" and "Returned Mail Ballot Totals" PDFs
  Collin   "Totals by Site Through <date>" PDF (includes today's check-ins so far)
  Comal    daily lists of in-person voters, counted (only the count is kept)
  Tarrant  "Early Voting In Person Totals" PDF, posted each morning with the in-person total through the
           previous day (the state's file had Tarrant at 16 in-person votes on day 1; the county reported 50,409).

Writes data/county_reports.json: {county: {in_person, through, posted, url}}. Used by early_vote.py only where the
state's own count for that county is lower.
"""
import io
import json
import re
import subprocess
import time
from datetime import datetime, timezone

HARRIS_PDF = "https://appfiles.harrisvotes.com/harrisvotes/prd/docs/Uploads/EVPA_unofficial.pdf"
TARRANT_PDF = "https://www.tarrantcountytx.gov/content/dam/main/elections/2026/1126/ev_reports/Early_Voting_Daily_Totals.pdf"


BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def get_bytes(url, referer=None):
    # some county sites (Denton) refuse requests that don't look like a browser
    cmd = ["curl", "-sL", "-f", "-m", "60", "-A", BROWSER_UA, "-H", "Accept: text/html,application/pdf,*/*"]
    if referer:
        cmd += ["-e", referer]
    for attempt in range(3):                     # county sites hiccup (Denton and Collin, Oct. 21, 4:16 p.m.)
        r = subprocess.run(cmd + [url], capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout
        time.sleep(5 * (attempt + 1))
    raise ValueError(f"no response from {url} after 3 tries (curl exit {r.returncode})")


def links(page_url, pattern):
    """(link text, absolute URL) for links on a county page whose text or address matches pattern."""
    from urllib.parse import urljoin
    import html as H
    page = get_bytes(page_url).decode("utf-8", "ignore")
    out = []
    for href, text in re.findall(r'href=["\']([^"\']+)["\'][^>]*>(.{0,300}?)</a>', page, re.S):
        text = H.unescape(re.sub(r"<[^>]+>|\s+", " ", text)).strip()
        if re.search(pattern, text + " " + href, re.I):
            out.append((text, urljoin(page_url, H.unescape(href))))
    return out


def parse_tarrant(text):
    """Header line 'Total 10/19 10/20 ...' (one column per day) then the row 'Total 50,409 50,409 ...':
    cumulative in-person votes first, then each day. Returns (in_person, last day 'MM/DD', that day's votes, posted)."""
    lines = [ln.split() for ln in text.splitlines() if ln.strip().startswith("Total")]
    head = next((ln for ln in lines if any("/" in x for x in ln)), [])
    row = next((ln for ln in lines if len(ln) >= 2 and all(re.fullmatch(r"[\d,]+", x) for x in ln[1:])), None)
    if not row:
        raise ValueError("no Total row in Tarrant report")
    days = [x for x in head if re.fullmatch(r"\d{1,2}/\d{1,2}", x)]
    if days and len(row) - 2 != len(days):
        raise ValueError(f"Tarrant report: {len(days)} day columns but {len(row) - 2} numbers")
    posted = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})\s+(\d{1,2}:\d{2}:\d{2}\s*[AP]M)", text)
    num = lambda x: int(x.replace(",", ""))
    return num(row[1]), days[-1] if days else None, num(row[-1]), " ".join(posted.groups()) if posted else None


def parse_harris(text):
    """Header '19-Oct 20-Oct ... 30-Oct' (one column per early-voting day). After the polling places come four rows
    of numbers only: in-person check-ins, mail ballots received, total early voters, ballots mailed. Each has one
    value per day so far, '0000000000' for days to come, then the total. Returns (in_person, mail, last day
    'MM/DD/2026', that day's in-person check-ins)."""
    months = {"Oct": 10, "Nov": 11}
    head = next((ln for ln in text.splitlines() if re.search(r"\b\d{1,2}-Oct\b", ln)), "")
    days = [f"{months[m]:02d}/{int(d):02d}/2026" for d, m in re.findall(r"\b(\d{1,2})-(Oct|Nov)\b", head)]
    num_rows = [ln.split() for ln in text.splitlines()
                if ln.strip() and all(re.fullmatch(r"[\d,]+|0{6,}", t) for t in ln.split()) and len(ln.split()) >= 3]
    if len(num_rows) < 3:
        raise ValueError("no total rows in Harris report")
    num = lambda t: int(t.replace(",", ""))
    def row(r):
        # days still to come are shown as "0000000000" or, since Oct. 21, as "0"
        vals = [num(t) for t in r[:-1]]
        if sum(vals) != num(r[-1]):
            raise ValueError(f"Harris report: days {vals} do not add up to {r[-1]}")
        return vals, num(r[-1])
    (ip_days, ip), (mail_days, mail), (_, total) = row(num_rows[0]), row(num_rows[1]), row(num_rows[2])
    if ip + mail != total:
        raise ValueError("Harris report: in person + mail does not match total early voters")
    n = max((i + 1 for i, v in enumerate(ip_days) if v > 0), default=0)      # days with in-person check-ins
    if not n or n > len(days):
        raise ValueError(f"Harris report: {n} days of check-ins for {len(days)} day columns")
    return ip, mail, days[n - 1], ip_days[n - 1]


def pdf_text(raw):
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)


def check_date(rec):
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    if rec.get("through") and datetime.strptime(rec["through"], "%m/%d/%Y").date() > today:
        raise ValueError(f"report says it runs through {rec['through']}, after today; the format may have changed")
    return rec


DENTON_PAGE = "https://www.votedenton.gov/early-voting-election-day-rosters/"
COLLIN_PAGE = "https://www.collincountytx.gov/elections/rosters"
COMAL_PAGE = "https://www.comalcounty.gov/264/Archived-Data"


def parse_denton_inperson(text):
    """'10/19 10/20 Total' then 'Daily Totals / Election Total 34740 31563 66303'. Returns (in_person, last day
    'MM/DD/2026', that day's votes)."""
    head = next((ln for ln in text.splitlines() if re.match(r"\s*\d{1,2}/\d{1,2}(\s+\d{1,2}/\d{1,2})*\s+Total", ln)), "")
    days = re.findall(r"\d{1,2}/\d{1,2}", head)
    m = re.search(r"Daily Totals / Election Total\s+([\d,\s]+)", text)
    if not days or not m:
        raise ValueError("no totals row in Denton report")
    vals = [int(v.replace(",", "")) for v in m.group(1).split()][:len(days) + 1]
    if len(vals) != len(days) + 1 or sum(vals[:-1]) != vals[-1]:
        raise ValueError(f"Denton report: days {vals[:-1]} do not add up to {vals[-1:]}")
    return vals[-1], f"{days[-1]}/2026", vals[-2]


def parse_denton_mail(text):
    """Row ' Denton County 394 399 ... ': mail ballots returned per day under a header of dates, with or without a
    final Total column (Denton dropped it on Oct. 26). Returns the total returned."""
    head = next((ln for ln in text.splitlines() if re.match(r"\s*\d{1,2}/\d{1,2}(\s+\d{1,2}/\d{1,2})+", ln)), "")
    days = re.findall(r"\d{1,2}/\d{1,2}", head)
    m = re.search(r"Denton County\s+([\d,\s]+)", text)
    if not m or not days:
        raise ValueError("no county row in Denton mail report")
    vals = [int(v.replace(",", "")) for v in m.group(1).split()]
    if "Total" in head:
        vals = vals[:len(days) + 1]
        if len(vals) != len(days) + 1 or sum(vals[:-1]) != vals[-1]:
            raise ValueError("Denton mail report does not add up")
        return vals[-1]
    vals = vals[:len(days)]
    if len(vals) != len(days):
        raise ValueError(f"Denton mail report: {len(days)} dates but {len(vals)} numbers")
    return sum(vals)


def parse_collin(text):
    """'Check-in Date Range: 10/19/2026 through 10/21/2026' ... 'Total' / '82,478'. Returns (in_person, through)."""
    rng = re.search(r"Check-in Date Range:\s*(\d{1,2}/\d{1,2}/\d{4})\s+through\s+(\d{1,2}/\d{1,2}/\d{4})", text)
    tot = re.findall(r"\bTotal\s*\n\s*([\d,]+)\s*\n", text + "\n")
    if not rng or not tot:
        raise ValueError("no date range or total in Collin report")
    sites = [int(v.replace(",", "")) for v in re.findall(r"\bEV\d{3}\s*\n\s*([\d,]+)", text)]
    total = int(tot[-1].replace(",", ""))
    if sites and sum(sites) != total:
        raise ValueError(f"Collin report: sites add up to {sum(sites)}, total says {total}")
    m, d, y = rng.group(2).split("/")
    return total, f"{int(m):02d}/{int(d):02d}/{y}"


def count_voter_ids(text):
    """Number of distinct voter IDs (10 digits) on a voter list. Only the count leaves this function."""
    return len(set(re.findall(r"(?<!\d)(\d{10})(?!\d)", text)))


def fetch_denton():
    lk = links(DENTON_PAGE, r"ev_by_day_poll_pad|Returned_by_day")
    ip_url = next(u for t, u in lk if "ev_by_day_poll_pad" in u)
    ip, through, last = parse_denton_inperson(pdf_text(get_bytes(ip_url, DENTON_PAGE)))
    mail_url = next((u for t, u in lk if "Returned_by_day" in u), None)
    mail = parse_denton_mail(pdf_text(get_bytes(mail_url, DENTON_PAGE))) if mail_url else 0
    return dict(in_person=ip, mail=mail, through=through, last_day=last, url=DENTON_PAGE,
                source="Denton County daily early-vote totals")


def fetch_collin():
    lk = [(t, u) for t, u in links(COLLIN_PAGE, r"Totals by Site Through") if u.lower().split("?")[0].endswith(".pdf")]
    if not lk:
        raise ValueError("no 'Totals by Site Through' report on Collin's page")
    ip, through = parse_collin(pdf_text(get_bytes(lk[0][1], COLLIN_PAGE)))
    return dict(in_person=ip, through=through, last_day=0, url=COLLIN_PAGE, source="Collin County totals by site")


def fetch_comal(cache):
    """Comal posts each day's list of in-person voters. Count the voters on each day's list (cached by document,
    so each list is read once) and add them up."""
    lk = links(COMAL_PAGE, r"\d{2}-\d{2}-2026, GENERAL ELECTION IN PERSON")
    days = {}
    for text, url in lk:
        d = re.search(r"(\d{2})-(\d{2})-2026", text)
        if d:
            days[f"{d.group(1)}/{d.group(2)}/2026"] = url
    if not days:
        raise ValueError("no daily in-person lists on Comal's page")
    counts = {}
    for day, url in days.items():
        doc = url.rstrip("/").split("/")[-1]
        if doc not in cache:
            cache[doc] = count_voter_ids(pdf_text(get_bytes(url, COMAL_PAGE)))
        counts[day] = cache[doc]
    last = max(days, key=lambda x: datetime.strptime(x, "%m/%d/%Y"))
    return dict(in_person=sum(counts.values()), through=last, last_day=counts[last], by_day=counts, url=COMAL_PAGE,
                source="Comal County daily in-person voter lists (counted)")


def keep_last_good(out, prev):
    """A county whose source failed this run keeps its last good report (marked with when it last worked), so a
    website hiccup doesn't drop it back to the state's older numbers. The error stays visible to the lag check."""
    for name, rec in out.items():
        old = (prev or {}).get(name, {})
        if rec.get("error") and old.get("in_person"):
            out[name] = dict(old, error=rec["error"], stale=True, last_good=old.get("last_good") or prev_fetched(prev))
    return out


def prev_fetched(prev):
    return (prev or {}).get("__fetched")


def fetch_county_reports():
    out = {}
    try:
        n, through, last, posted = parse_tarrant(pdf_text(get_bytes(TARRANT_PDF)))
        out["Tarrant"] = check_date(dict(in_person=n, through=f"{through}/2026" if through else None, last_day=last,
                                         posted=posted, url=TARRANT_PDF, source="Tarrant County daily early-vote report"))
    except Exception as e:
        out["Tarrant"] = dict(error=f"{type(e).__name__}: {e}")
    try:
        ip, mail, through, last = parse_harris(pdf_text(get_bytes(HARRIS_PDF)))
        out["Harris"] = check_date(dict(in_person=ip, mail=mail, through=through, last_day=last, url=HARRIS_PDF,
                                        source="Harris County Clerk daily early-vote report"))
    except Exception as e:
        out["Harris"] = dict(error=f"{type(e).__name__}: {e}")
    try:
        prev_all = json.load(open("data/county_reports.json"))
    except (OSError, ValueError):
        prev_all = {}
    prev_cache = prev_all.get("comal_cache", {})
    for name, fn in (("Denton", fetch_denton), ("Collin", fetch_collin), ("Comal", lambda: fetch_comal(prev_cache))):
        try:
            out[name] = check_date(fn())
        except Exception as e:
            out[name] = dict(error=f"{type(e).__name__}: {e}")
    prev = dict(prev_all.get("counties") or {}, __fetched=prev_all.get("fetched"))
    out = keep_last_good(out, prev)
    json.dump(dict(fetched=datetime.now(timezone.utc).isoformat(timespec="seconds"), counties=out, comal_cache=prev_cache),
              open("data/county_reports.json", "w"), indent=1)
    return ", ".join(f"{k} {v['in_person']:,} through {v['through']}" if "in_person" in v else f"{k} {v['error']}"
                     for k, v in out.items())


if __name__ == "__main__":
    print(fetch_county_reports())

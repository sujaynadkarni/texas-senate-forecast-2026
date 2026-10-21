"""Official county early-vote reports that come out before the state's file is complete.

  Harris   "Daily Record of Early Voting Check-ins" PDF, updated each evening: in-person check-ins per day and
           mail ballots received (the state's file had Harris at 30,460 in person after day 2; the county, 204,570).
  Tarrant  "Early Voting In Person Totals" PDF, posted each morning with the in-person total through the
           previous day (the state's file had Tarrant at 16 in-person votes on day 1; the county reported 50,409).

Writes data/county_reports.json: {county: {in_person, through, posted, url}}. Used by early_vote.py only where the
state's own count for that county is lower.
"""
import io
import json
import re
import subprocess
from datetime import datetime, timezone

HARRIS_PDF = "https://appfiles.harrisvotes.com/harrisvotes/prd/docs/Uploads/EVPA_unofficial.pdf"
TARRANT_PDF = "https://www.tarrantcountytx.gov/content/dam/main/elections/2026/1126/ev_reports/Early_Voting_Daily_Totals.pdf"


def get_bytes(url):
    return subprocess.run(["curl", "-sL", "-f", "-m", "60", "-A", "Mozilla/5.0 (tx-senate-forecast)", url],
                          capture_output=True, check=True).stdout


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
    json.dump(dict(fetched=datetime.now(timezone.utc).isoformat(timespec="seconds"), counties=out),
              open("data/county_reports.json", "w"), indent=1)
    return ", ".join(f"{k} {v['in_person']:,} through {v['through']}" if "in_person" in v else f"{k} {v['error']}"
                     for k, v in out.items())


if __name__ == "__main__":
    print(fetch_county_reports())

"""Official county early-vote reports that come out before the state's file is complete.

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


def pdf_text(raw):
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)


def fetch_county_reports():
    out = {}
    try:
        n, through, last, posted = parse_tarrant(pdf_text(get_bytes(TARRANT_PDF)))
        out["Tarrant"] = dict(in_person=n, through=f"{through}/2026" if through else None, last_day=last, posted=posted,
                              url=TARRANT_PDF, source="Tarrant County daily early-vote report")
    except Exception as e:
        out["Tarrant"] = dict(error=f"{type(e).__name__}: {e}")
    json.dump(dict(fetched=datetime.now(timezone.utc).isoformat(timespec="seconds"), counties=out),
              open("data/county_reports.json", "w"), indent=1)
    return ", ".join(f"{k} {v['in_person']:,} through {v['through']}" if "in_person" in v else f"{k} {v['error']}"
                     for k, v in out.items())


if __name__ == "__main__":
    print(fetch_county_reports())

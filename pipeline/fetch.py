"""Fetch live inputs: polls, prediction markets, early-vote turnout, election-night results.

Each source writes its own file under data/. If a source fails, the previous file is kept
and the failure is recorded in data/fetch_log.json so the site can show which data is stale.
Run from project root:  python3 pipeline/fetch.py
"""
import base64, csv, json, re, subprocess, sys, traceback
from datetime import datetime, timezone

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
SOS = "https://goelect.txelections.civixapps.com/api-ivis-system/api"
GENERAL_ID = 53815


NAME_FIX = {"Dewitt": "DeWitt", "Lasalle": "La Salle", "Mcculloch": "McCulloch", "Mclennan": "McLennan", "Mcmullen": "McMullen"}
county_name = lambda n: NAME_FIX.get(n.title(), n.title())


def get(url):
    # curl: the SOS API refuses Python's default user agent
    out = subprocess.run(["curl", "-sL", "-m", "60", "-A", "Mozilla/5.0 (tx-senate-forecast)", url],
                         capture_output=True, check=True).stdout
    return out.decode("utf-8")


def sos_json(url):
    d = json.loads(get(url))
    return json.loads(base64.b64decode(d["upload"]))


# ---- polls -----------------------------------------------------------------------------------
def fetch_polls():
    raw = get("https://en.wikipedia.org/w/index.php?title=2026_United_States_Senate_election_in_Texas&action=raw")
    open("data/raw/wiki_txsen.txt", "w").write(raw)
    rows = parse_polls(raw)
    if len(rows) < 20:
        raise ValueError(f"only {len(rows)} polls parsed; page layout may have changed")
    with open("data/polls.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    return f"{len(rows)} polls"


def parse_polls(txt):
    ge = txt.index("== General election ==")
    start = txt.index("! Poll source", txt.index("=== Polling ===", ge))
    tbl = txt[start:txt.index("|}", start)]
    tbl = re.sub(r"<ref[^>]*/>", "", tbl)
    tbl = re.sub(r"<ref[^>]*>.*?</ref>", "", tbl, flags=re.S)
    tbl = re.sub(r"\{\{[Ee]fn[^}]*\}\}", "", tbl)

    def clean(c):
        c = re.sub(r"^\s*(style|rowspan|colspan)[^|]*\|", "", c)
        c = re.sub(r"\{\{[Pp]arty shading/\w+\}\}\s*\|", "", c)
        c = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", c)
        c = re.sub(r"<br\s*/?>|<!--.*?-->", " ", c)
        c = re.sub(r"\{\{nbsp\}\}|\{\{sdash\}\}|'''|''", "", c)
        return re.sub(r"\s+", " ", c).strip()

    def pct(s):
        m = re.search(r"([\d.]+)%", s); return float(m.group(1)) if m else None

    out, carry = [], {}
    for r in tbl.split("\n|-")[1:]:
        raw = [x for x in re.split(r"\n\|", "\n" + r.strip()) if x.strip()]
        cells = [clean(c) for c in raw]
        if len(cells) == 8:
            src, date = cells[0], cells[1]
            carry = {"src": src, "date": date} if "rowspan" in raw[0] else {}
            sample, pax, tal = cells[2], cells[4], cells[5]
        elif len(cells) == 6 and carry:
            src, date = carry["src"], carry["date"]
            sample, pax, tal = cells[0], cells[2], cells[3]
        else:
            continue
        p, t = pct(pax), pct(tal)
        if p is None or t is None:
            continue
        m = re.search(r"([\d,]+)\s*\((\w+)\)", sample)
        out.append(dict(pollster=src, dates=date, n=int(m.group(1).replace(",", "")) if m else "",
                        pop=m.group(2) if m else re.sub(r"[^A-Z]", "", sample),
                        paxton=p, talarico=t, margin_D=round(t - p, 1)))
    return out


# ---- prediction markets ----------------------------------------------------------------------
def fetch_markets():
    k = json.loads(get("https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker=SENATETX-26"))["markets"]
    kd = {m["yes_sub_title"]: m for m in k}
    tal_k = float(kd["James Talarico"]["last_price_dollars"])
    vol_k = sum(float(m["volume_fp"]) for m in k)
    p = json.loads(get("https://gamma-api.polymarket.com/public-search?q=Texas%20Senate%20Election%20Winner&limit_per_type=10"))
    ev = [e for e in p["events"] if e["title"] == "Texas Senate Election Winner"][0]
    dem = [m for m in ev["markets"] if m["question"].startswith("Will the Democrats win")][0]
    tal_p = float(json.loads(dem["outcomePrices"])[0])
    out = {"fetched": NOW, "markets": [
        {"source": "Kalshi", "talarico": tal_k, "paxton": round(1 - tal_k, 3), "volume_usd": round(vol_k),
         "url": "https://kalshi.com/markets/senatetx/texas-senate-race"},
        {"source": "Polymarket", "talarico": tal_p, "paxton": round(1 - tal_p, 3), "volume_usd": round(float(ev["volume"])),
         "url": "https://polymarket.com/event/texas-senate-election-winner"}]}
    json.dump(out, open("data/markets.json", "w"), indent=1)
    return f"Kalshi {tal_k:.2f}, Polymarket {tal_p:.2f}"


# ---- early-vote turnout ----------------------------------------------------------------------
def fetch_turnout():
    elections = sos_json(f"{SOS}/v1/getFile?type=EVR_ELECTION")["elections"]
    dates = [d["date"] for d in [e for e in elections if e["id"] == GENERAL_ID][0]["early_voting_dates"]]
    today = datetime.now().strftime("%m/%d/%Y")
    latest = None
    for d in reversed([d for d in dates if datetime.strptime(d, "%m/%d/%Y") <= datetime.strptime(today, "%m/%d/%Y")]):
        try:
            j = sos_json(f"{SOS}/v1/getFile?type=EVR_EARLYVOTING&electionId={GENERAL_ID}&electionDate={d}")
        except Exception:
            continue
        if j.get("turnout_by_county"):
            latest = (d, j); break
    if not latest:
        raise ValueError("no early-vote file available yet")
    d, j = latest
    # keep every day's file so the site can compare day N of 2026 with day N of 2022
    daily_path = "data/ev_daily_2026.json"
    try:
        daily = json.load(open(daily_path))
    except (OSError, ValueError):
        daily = {}
    for dd in dates:
        if datetime.strptime(dd, "%m/%d/%Y") > datetime.strptime(today, "%m/%d/%Y"):
            continue
        if dd in daily and dd != d and daily[dd].get("final"):
            continue
        try:
            jj = j if dd == d else sos_json(f"{SOS}/v1/getFile?type=EVR_EARLYVOTING&electionId={GENERAL_ID}&electionDate={dd}")
        except Exception:
            continue
        if not jj.get("turnout_by_county"):
            continue
        daily[dd] = {"final": dd != d, "updated": jj.get("date_updated"),
                     "counties": {county_name(c["name"]): [c["total_in_person_votes_for_election"], c["total_mail_votes_for_election"],
                                                          c["in_person_votes_on_date"]] for c in jj["turnout_by_county"]}}
    json.dump(daily, open(daily_path, "w"))
    counties = {county_name(c["name"]): {"registered": c["registered_voters"], "in_person": c["total_in_person_votes_for_election"],
                                    "mail": c["total_mail_votes_for_election"], "in_person_today": c["in_person_votes_on_date"]}
                for c in j["turnout_by_county"]}
    out = {"fetched": NOW, "as_of_date": d, "state_updated": j.get("date_updated"), "counties": counties}
    json.dump(out, open("data/turnout.json", "w"))
    tot = sum(c["in_person"] + c["mail"] for c in counties.values())
    return f"{d}: {tot:,} early votes"


# ---- election-night results ------------------------------------------------------------------
def fetch_results():
    j = sos_json(f"{SOS}/s3/enr/election/countyInfo/{GENERAL_ID}")
    counties = {}
    for c in j.values():
        sen = [r for r in c["Races"].values() if r["N"].strip() == "U. S. SENATOR"]
        if not sen:
            continue
        r = sen[0]
        cand = {x["LN"]: x["V"] for x in r["C"].values()}
        counties[county_name(c["N"])] = {"talarico": cand.get("TALARICO", 0), "paxton": cand.get("PAXTON", 0), "total": r.get("T", 0),
                                    "precincts_reporting": r.get("PR", 0), "precincts_total": r.get("TP", 0)}
    out = {"fetched": NOW, "counties": counties}
    json.dump(out, open("data/results.json", "w"))
    tot = sum(c["total"] for c in counties.values())
    return f"{len(counties)} counties, {tot:,} votes counted"


def main():
    log = {}
    for name, fn in (("polls", fetch_polls), ("markets", fetch_markets), ("turnout", fetch_turnout), ("results", fetch_results)):
        try:
            log[name] = {"ok": True, "at": NOW, "detail": fn()}
        except Exception as e:
            log[name] = {"ok": False, "at": NOW, "detail": f"{type(e).__name__}: {e}"}
            traceback.print_exc()
        print(f"{name:<8} {'OK ' if log[name]['ok'] else 'FAIL'} {log[name]['detail']}")
    json.dump(log, open("data/fetch_log.json", "w"), indent=1)
    return 0 if all(v["ok"] for k, v in log.items() if k in ("polls", "markets")) else 1


if __name__ == "__main__":
    sys.exit(main())

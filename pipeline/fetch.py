"""Fetch live inputs for every race in races.py: polls, prediction markets, early-vote turnout,
election-night results.

Each source writes its own file under data/. If a source fails, the previous file is kept
and the failure is recorded in data/fetch_log.json so the site can show which data is stale.
Run from project root:  PYTHONPATH=pipeline python3 pipeline/fetch.py
"""
import base64, csv, json, re, subprocess, sys, time, traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, "pipeline")
from races import RACES

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


def sos_json(url, tries=4):
    # The state's server sometimes answers with an empty body for a moment (Oct. 20, 9 p.m.); retry before failing.
    for i in range(tries):
        try:
            d = json.loads(get(url))
            return json.loads(base64.b64decode(d["upload"]))
        except (ValueError, KeyError, subprocess.CalledProcessError):
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


# ---- polls -----------------------------------------------------------------------------------
def fetch_polls():
    out = []
    for key, race in RACES.items():
        raw = get(f"https://en.wikipedia.org/w/index.php?title={race['wiki']}&action=raw")
        open(f"data/raw/wiki_{key}.txt", "w").write(raw)
        rows = parse_polls(raw, race["d"], race["r"])
        if len(rows) < 10:
            raise ValueError(f"{key}: only {len(rows)} polls parsed; page layout may have changed")
        with open(f"data/polls_{key}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
        out.append(f"{key} {len(rows)}")
    return ", ".join(out) + " polls"


SAMPLE = re.compile(r"[\d,]+\s*\((LV|RV|A)\)")
WIKI_MARKUP = re.compile(r"\{\{nbsp\}\}|\{\{sdash\}\}|'{2,3}")


def parse_polls(txt, d_name, r_name):
    """Head-to-head table in the General election section. Rows: pollster, dates, sample, MoE, then one
    column per candidate in the order the table header lists them."""
    ge = txt.index("== General election ==")
    pol = re.search(r"===\s*Polling\s*===", txt[ge:]).start() + ge
    start = txt.index("! Poll source", pol)
    tbl = txt[start:txt.index("|}", start)]
    header = tbl.split("\n|-")[0]
    di, ri = header.find(d_name), header.find(r_name)
    if di < 0 or ri < 0:
        raise ValueError(f"candidate columns not found for {d_name}/{r_name}")
    first, second = ("d", "r") if di < ri else ("r", "d")
    tbl = re.sub(r"<ref[^>]*/>", "", tbl)
    tbl = re.sub(r"<ref[^>]*>.*?</ref>", "", tbl, flags=re.S)
    tbl = re.sub(r"\{\{[Ee]fn[^}]*\}\}", "", tbl)

    def clean(c):
        c = re.sub(r"^\s*(style|rowspan|colspan)[^|]*\|", "", c)
        c = re.sub(r"\{\{[Pp]arty shading/\w+\}\}\s*\|", "", c)
        c = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", c)
        c = re.sub(r"<br\s*/?>|<!--.*?-->", " ", c)
        c = WIKI_MARKUP.sub("", c)
        return re.sub(r"\s+", " ", c).strip()

    def pct(s):
        m = re.search(r"([\d.]+)%", s); return float(m.group(1)) if m else None

    out, carry = [], {}
    for r in tbl.split("\n|-")[1:]:
        raw = [x for x in re.split(r"\n\|", "\n" + r.strip()) if x.strip()]
        cells = [clean(c) for c in raw]
        if len(cells) >= 7 and pct(cells[4]) is not None:                   # full row
            src, date = cells[0], cells[1]
            carry = {"src": src, "date": date} if "rowspan" in raw[0] else {}
            sample, a, b = cells[2], cells[4], cells[5]
        elif carry and SAMPLE.search(cells[0]):                              # follow-up row of a rowspan: new sample (LV/RV)
            src, date = carry["src"], carry["date"]
            k = 2 if "±" in cells[1] else 1                                   # its own margin-of-error cell, or shared
            if len(cells) < k + 2:
                continue
            sample, a, b = cells[0], cells[k], cells[k + 1]
        else:
            continue
        va, vb = pct(a), pct(b)
        if va is None or vb is None:
            continue
        vals = {first: va, second: vb}
        m = re.search(r"([\d,]+)\s*\((\w+)\)", sample)
        out.append(dict(pollster=src, dates=date, n=int(m.group(1).replace(",", "")) if m else "",
                        pop=m.group(2) if m else re.sub(r"[^A-Z]", "", sample),
                        d=vals["d"], r=vals["r"], margin_D=round(vals["d"] - vals["r"], 1)))
    return out


# ---- prediction markets ----------------------------------------------------------------------
def fetch_markets():
    out, summary = {"fetched": NOW}, []
    for key, race in RACES.items():
        k = json.loads(get(f"https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker={race['kalshi_event']}"))["markets"]
        kd = {m["yes_sub_title"]: m for m in k}
        d_k = float(kd[race["kalshi_d"]]["last_price_dollars"])
        vol_k = sum(float(m["volume_fp"]) for m in k)
        p = json.loads(get("https://gamma-api.polymarket.com/public-search?q=" + race["poly_event"].replace(" ", "%20") + "&limit_per_type=10"))
        ev = [e for e in p["events"] if e["title"] == race["poly_event"]][0]
        dem = [m for m in ev["markets"] if m["question"].startswith(race["poly_d_question"])][0]
        d_p = float(json.loads(dem["outcomePrices"])[0])
        out[key] = [dict(source="Kalshi", d=d_k, volume_usd=round(vol_k), url=race["kalshi_url"]),
                    dict(source="Polymarket", d=d_p, volume_usd=round(float(ev["volume"])), url=race["poly_url"])]
        summary.append(f"{key}: Kalshi {d_k:.2f}, Polymarket {d_p:.2f}")
    json.dump(out, open("data/markets.json", "w"), indent=1)
    return "; ".join(summary)


# ---- early-vote turnout (shared by all races) -------------------------------------------------
def fetch_turnout():
    elections = sos_json(f"{SOS}/v1/getFile?type=EVR_ELECTION")["elections"]
    dates = [d["date"] for d in [e for e in elections if e["id"] == GENERAL_ID][0]["early_voting_dates"]]
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%m/%d/%Y")    # Texas date, not the server's
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
    out, summary = {"fetched": NOW}, []
    for key, race in RACES.items():
        counties = {}
        for c in j.values():
            rr = [r for r in c["Races"].values() if r["N"].strip() == race["results_race"]]
            if not rr:
                continue
            r = rr[0]
            cand = {x["LN"]: x["V"] for x in r["C"].values()}
            counties[county_name(c["N"])] = {"d": cand.get(race["results_d"], 0), "r": cand.get(race["results_r"], 0),
                                             "total": r.get("T", 0), "precincts_reporting": r.get("PR", 0),
                                             "precincts_total": r.get("TP", 0)}
        if len(counties) < 254:
            raise ValueError(f"{key}: results race found in only {len(counties)} counties")
        out[key] = counties
        summary.append(f"{key} {sum(c['total'] for c in counties.values()):,}")
    json.dump(out, open("data/results.json", "w"))
    return "votes counted: " + ", ".join(summary)


def main():
    log = {}
    from fetch_live import fetch_live
    from county_reports import fetch_county_reports
    for name, fn in (("polls", fetch_polls), ("markets", fetch_markets), ("turnout", fetch_turnout), ("results", fetch_results),
                     ("live", fetch_live), ("county", fetch_county_reports)):
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

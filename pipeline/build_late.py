"""Build build/late.html ("Still counting": Mississippi and Alaska) from data/late_count.json.
Uses the main page's stylesheet so the tab looks the same. Skips quietly if there is no projection yet."""
import html, json, os, re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SRC = "data/late_count.json"
if not os.path.exists(SRC):
    print("no data/late_count.json yet; late.html not built")
    raise SystemExit(0)
d = json.load(open(SRC))
tpl = open("site/template.html").read()
css = re.search(r"<style>(.*?)</style>", tpl, re.S).group(1)
E = html.escape
CT = ZoneInfo("America/Chicago")


def when(iso):
    if not iso:
        return ""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(CT)
    return t.strftime("%b. %-d, %-I:%M %p").replace("AM", "a.m.").replace("PM", "p.m.") + " Central"


def color(p):
    return {"D": "var(--dem)", "R": "var(--rep)"}.get(p, "var(--ink-2)")


def pct(x, nd=0):
    return f"{x * 100:.{nd}f}%"


def chance(p):
    if p >= 0.995: return ">99%"
    if p <= 0.005: return "<1%"
    return pct(p)


def lead(m):
    return "Even" if abs(m) < 0.05 else (f"D+{m:.1f}" if m > 0 else f"R+{-m:.1f}")


ORDER = ["ms_senate", "ak_senate", "ak_governor"]
sections = []
for k in ORDER:
    r = d["races"].get(k)
    if not r:
        continue
    c = {x["name"]: x for x in r["candidates"]}
    main = [n for n in sorted(r["win"], key=r["win"].get, reverse=True)][:2]
    if r["dem"] and r["rep"]:
        main = [r["dem"], r["rep"]]
    fav = max(r["win"], key=r["win"].get)
    p = r["win"][fav]
    rt = r.get("rating") or "Toss-up"
    rcol = "var(--dem)" if rt.endswith("Democratic") else "var(--rep)" if rt.endswith("Republican") else "var(--ink-2)"
    head = f"{E(rt)}" + (f": {E(fav)} favored" if rt != "Toss-up" else "")
    T = r["counted_total"]
    cand_rows = "".join(
        f"<tr><td class='name'><span style='color:{color(c[n]['party'])}'>{E(c[n]['full'])}</span> <span class='sub'>({c[n]['party'] if c[n]['party'] in 'DR' else 'other'})</span></td>"
        f"<td>{r['counted'][n]:,}</td><td>{pct(r['counted'][n] / T, 1)}</td>"
        f"<td>{r['first_round'][n]['mid']:.1f}%<span class='sub'>{r['first_round'][n]['lo']:.1f}–{r['first_round'][n]['hi']:.1f}</span></td></tr>"
        for n in [x["name"] for x in r["candidates"]] if r["counted"][n] > 0)
    m = r["margin"]
    rcv_line = ""
    if r["rcv"]:
        rcv_line = (f"<li><strong>Ranked choice:</strong> no one passes 50% in the first round in {pct(r['rcv_share'])} of runs, so "
                    "last-place candidates are dropped and their voters' next choices count. Alaska publishes those rankings only "
                    "when it runs the official tally, so the model varies how they split.</li>")
    late_line = ""
    if r.get("late_lean") and r["dem"]:
        late_line = (f"<li><strong>Ballots counted late:</strong> mail and early ballots counted so far ran {lead(r['late_lean'][r['dem']] - r['late_lean'][r['rep']])} "
                     "against the overall count. Most ballots left are of this kind. In 2024 Alaska's late count moved results by 1 to 4 "
                     "points (the ranked-choice repeal led on election night and lost), so the model applies a quarter to all of that lean.</li>")
    swing_line = (f"<li><strong>Compared with 2024:</strong> counties that have reported are running {lead(r['swing_vs_2024'])} "
                  "against the 2024 presidential result; uncounted ballots in a county are projected from its own count "
                  "so far and that shifted 2024 result.</li>") if r.get("swing_vs_2024") is not None else ""
    place_rows = "".join(
        f"<tr><td class='name'>{E(x['name'])}</td><td>{x['pin']:.0f}%</td><td>{x['left']:,}</td><td>{lead(x['counted_margin'])}</td></tr>"
        for x in r["places"][:8])
    unit = "County" if r["unit"] == "county" else "District"
    prov_line = ("<li><strong>Provisional ballots:</strong> many of Mississippi's uncounted ballots are affidavit (provisional) "
                 "ballots, and many of those are rejected. The state keeps no statewide count of them and reported no 2024 totals "
                 "to the federal election survey, so the model assumes anywhere from about a third to all of the ballots left "
                 "end up counted.</li>") if r["state"] == "Mississippi" else ""
    sections.append(f"""
  <section class="col-wide rule-top late-race" id="{k}">
    <p class="kicker">{E(r['state'])} · {E(r['office'])}</p>
    <h2 class="late-h"><span class="rating" style="background:{rcol}">{E(rt)}</span>{E(fav) + " favored" if rt != "Toss-up" else "Too close to call"}</h2>
    <p class="section-dek">About <strong>{pct(r['share_in'])}</strong> of the expected vote is counted ({T:,} ballots); roughly
      <strong>{r['left_total']:,}</strong> are left. Projected final margin: <strong>{lead(m['mid'])}</strong>
      <span class="sans" style="color:var(--ink-3);font-size:15px">(90% range {lead(m['lo'])} to {lead(m['hi'])})</span>.</p>
    <div class="tbl-scroll"><table>
      <thead><tr><th>Candidate</th><th>Votes counted</th><th>Share now</th><th>Projected first round<span class="sub">90% range</span></th></tr></thead>
      <tbody>{cand_rows}</tbody></table></div>
    <ul class="late-notes">{swing_line}{prov_line}{late_line}{rcv_line}</ul>
    <h3 class="late-sub">Where the most votes are left</h3>
    <div class="tbl-scroll"><table>
      <thead><tr><th>{unit}</th><th>Counted</th><th>Votes left</th><th>Margin so far</th></tr></thead>
      <tbody>{place_rows}</tbody></table></div>
    <p class="byline">Results as of {when(r['source_time'])}.</p>
  </section>""")

page = f"""<title>Still Counting: Mississippi and Alaska</title>
<meta name="claude:viewport-fit-sides" content="cover">
<meta name="color-scheme" content="only light">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;500;600;700;800&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;0,8..60,700;1,8..60,400&display=swap">
<style>{css}
.late-race {{ margin-top: 34px; }}
th .sub {{ display: block; font-weight: 400; text-transform: none; letter-spacing: 0; }}
.late-h {{ font-family: var(--serif); font-size: clamp(26px, 5vw, 34px); font-weight: 700; margin: 0 0 8px; }}
.rating {{ display: inline-block; color: #fff; font: 800 13px var(--sans); letter-spacing: .05em; text-transform: uppercase; padding: 5px 9px; border-radius: 3px; margin: 0 10px 6px 0; vertical-align: middle; }}
.late-sub {{ font: 800 16px var(--sans); margin: 22px 0 6px; }}
.late-notes {{ font-size: 16px; color: var(--ink-2); padding-left: 20px; margin: 16px 0 0; display: grid; gap: 6px; max-width: var(--narrow); }}
.method {{ font-size: 16px; color: var(--ink-2); max-width: var(--narrow); }}
.method ol {{ padding-left: 20px; display: grid; gap: 6px; }}
</style>

<div class="wrap">
  <div class="col-wide mast">
    <span>2026 Forecast <span class="race">· Races still counting</span></span>
    <span class="status"><span class="dot" style="background:var(--warn)"></span><span>Updated {when(d['generated'])}</span></span>
  </div>
  <header class="col hero">
    <p class="kicker">Mississippi and Alaska</p>
    <h1>Still counting: what the ballots left could do</h1>
    <p class="dek">These races were too close to call after election night. This page projects the uncounted ballots from the votes
      already counted and from how each place has voted before, and runs the count 20,000 times.</p>
    <p class="section-dek sans" style="font-size:15px"><strong>Ratings:</strong> Toss-up, Lean, Likely or Safe, by how often a candidate wins across those runs (under 65%, 65–85%, 85–97%, 97% or more). A race projected within 1 point is never rated above Lean.</p>
  </header>
  <nav class="col-wide pagetabs" aria-label="Pages">
    <a href="index.html">Senate</a>
    <a href="governor.html">Governor</a>
    <a href="early.html">Early voting</a>
    <a href="late.html" aria-current="page">Still counting</a>
  </nav>
  {''.join(sections)}
  <section class="col-wide rule-top late-race method">
    <h2>How this projection works</h2>
    <ol>
      <li>Start with the votes counted so far in each county (Mississippi) or state House district (Alaska).</li>
      <li>Estimate the votes left in each place from how much of its expected vote is in.</li>
      <li>Project how those votes lean: the place's own count so far, blended with its 2024 result shifted by the swing seen in
        every reporting place. In Alaska, ballots counted after Election Day are mostly mail and early ballots, so they get part of
        the lean those ballots have shown.</li>
      <li>Run the count 20,000 times, each time shifting the uncounted vote statewide, place by place, and in how many ballots are
        really left. The share of runs each candidate wins sets the rating.</li>
      <li>Alaska uses ranked choice: when no one passes 50%, the last-place candidate is dropped and their voters' next choices
        count. In Alaska's 2022 House tally, about half of the eliminated Republican's voters went to the other Republican,
        29% to the Democrat, and 21% had no next choice; the model varies around those rates.</li>
    </ol>
    <p><strong>What it cannot see:</strong> provisional (affidavit) ballots that may be rejected, ballots still arriving by mail, and
      Alaska's actual second choices, which are released only with the official ranked-choice tally. Mississippi's count is close
      enough that a recount is possible.</p>
  </section>
  <footer class="col-wide">
    <p>Vote counts: NBC News / Associated Press results pages. 2024 county results: NBC News. Projection: this site's model.
      Not a call; only the states certify a winner.</p>
  </footer>
</div>
"""
os.makedirs("build", exist_ok=True)
open("build/late.html", "w").write(page)
print(f"build/late.html {len(page) / 1024:.0f} KB")

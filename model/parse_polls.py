"""Parse the Paxton vs Talarico head-to-head poll table from the Wikipedia page source."""
import re, csv
lines = open("data/raw/wiki_txsen.txt").read().split("\n")[3005:4358]
txt = "\n".join(lines)
# first table after aggregates that has Paxton then Talarico header
start = txt.index("! Poll source")
end = txt.index("|}", start)
tbl = txt[start:end]
tbl = re.sub(r"<ref[^>]*/>", "", tbl)
tbl = re.sub(r"<ref[^>]*>.*?</ref>", "", tbl, flags=re.S)
tbl = re.sub(r"\{\{[Ee]fn[^}]*\}\}", "", tbl)
rows = tbl.split("\n|-")[1:]
def clean(c):
    c = re.sub(r"^\s*(style|rowspan|colspan)[^|]*\|", "", c)          # drop cell attributes
    c = re.sub(r"\{\{[Pp]arty shading/\w+\}\}\s*\|", "", c)
    c = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", c)
    c = re.sub(r"\{\{nbsp\}\}|\{\{sdash\}\}|'''|''", "", c)
    return c.strip()
out, carry = [], {}
for r in rows:
    cells = [x for x in re.split(r"\n\|", "\n" + r.strip()) if x.strip()]
    raw = cells
    cells = [clean(c) for c in cells]
    # carry pollster/date from rowspan rows
    if len(cells) == 8:
        src, date = cells[0], cells[1]
        span = 'rowspan' in raw[0]
        carry = {"src": src, "date": date} if span else {}
        sample, moe, pax, tal = cells[2], cells[3], cells[4], cells[5]
    elif len(cells) == 6 and carry:
        src, date = carry["src"], carry["date"]
        sample, moe, pax, tal = cells[0], cells[1], cells[2], cells[3]
    else:
        continue
    def pct(s):
        m = re.search(r"([\d.]+)%", s); return float(m.group(1)) if m else None
    p, t = pct(pax), pct(tal)
    if p is None or t is None: continue
    m = re.search(r"([\d,]+)\s*\((\w+)\)", sample)
    n = int(m.group(1).replace(",", "")) if m else None
    pop = m.group(2) if m else re.sub(r"[^A-Z]", "", sample)
    out.append(dict(pollster=src, dates=date, n=n, pop=pop, paxton=p, talarico=t, margin_D=round(t - p, 1)))
with open("data/polls.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=out[0].keys()); w.writeheader(); w.writerows(out)
print(len(out), "poll rows")
for o in out[:40]: print(o)

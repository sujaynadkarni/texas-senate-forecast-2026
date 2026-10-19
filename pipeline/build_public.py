"""Standalone public site for GitHub Pages: full HTML documents with social preview tags.
  public/index.html (Senate), public/governor.html, public/early.html + public/share_*.png
Run after build_site.py and share_card.py."""
import html, json, os, re, sys
sys.path.insert(0, "pipeline")
from races import RACES, margin_label

BASE = (json.load(open("data/site.json")).get("url") or "https://sujaynadkarni.github.io/texas-senate-forecast-2026/")


def race_desc(key):
    d = json.load(open(f"site/data_{key}.json")); r = RACES[key]; p = d["needle"]["p"]
    m = margin_label(key, (2 * d["needle"]["median"] - 1) * 100, True)
    return d, (f"{r['d']} {round(p * 100)}%, {r['r']} {round((1 - p) * 100)}% to win (expected margin {m}). "
               "County map, polls, early vote and a live needle on election night. Updated daily.")


sen, sen_desc = race_desc("senate")
gov, gov_desc = race_desc("governor")
e = sen.get("early")
early_desc = ((f"{e['total']:,} Texans have voted so far. " if e else "") +
              "Every county's early vote compared with the same day in 2022, and what it suggests for the Senate and governor races.")
version = re.sub(r"\D", "", sen["generated"])[:12]

PAGES = [  # file, title, description, card
    ("index.html", "Texas Senate Forecast: Talarico vs. Paxton", sen_desc, "share_senate.png"),
    ("governor.html", "Texas Governor Forecast: Abbott vs. Hinojosa", gov_desc, "share_governor.png"),
    ("early.html", "Texas Early Vote Tracker", early_desc, "share_early.png"),
]
os.makedirs("public", exist_ok=True)
for fname, title, desc, card in PAGES:
    url = BASE + ("" if fname == "index.html" else fname)
    page = open(f"build/{fname}").read()
    page = re.sub(r"^<title>.*?</title>\s*", "", page, count=1)
    t, dsc = html.escape(title), html.escape(desc)
    img = f"{BASE}{card}?v={version}"
    head = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{t}</title>
<meta name="description" content="{dsc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Texas 2026 Forecast">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{dsc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{dsc}">
<meta name="twitter:image" content="{img}">
<style>:root{{color-scheme:only light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}body{{margin:0}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
</head>
<body>
"""
    open(f"public/{fname}", "w").write(head + page + "\n</body>\n</html>\n")
    print(f"public/{fname} {os.path.getsize(f'public/{fname}')/1024:.0f} KB")
open("public/.nojekyll", "w").write("")

"""Standalone public site for GitHub Pages: public/index.html (full HTML document with social
preview tags) + public/share.png. Run after export.py and share_card.py."""
import html, json, os, re
from datetime import datetime

d = json.load(open("site/data.json"))
url = d.get("site_url") or "https://sujaynadkarni.github.io/texas-senate-forecast-2026/"
version = re.sub(r"\D", "", d["generated"])[:12]
p = d["needle"]["p"]
m = (2 * d["needle"]["median"] - 1) * 100
margin = ("Talarico" if m >= 0 else "Paxton") + f" +{abs(m):.1f}"
title = "Texas Senate Forecast: Talarico vs. Paxton"
desc = (f"Talarico {round(p * 100)}%, Paxton {round((1 - p) * 100)}% to win (expected margin {margin}). "
        "County map, polls, early vote and a live needle on election night. Updated daily.")

page = open("build/index.html").read()
page = re.sub(r"^<title>.*?</title>\s*", "", page, count=1)
head = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Texas Senate Forecast">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{url}share.png?v={version}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Forecast needle: Talarico {round(p * 100)}%, Paxton {round((1 - p) * 100)}%">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(title)}">
<meta name="twitter:description" content="{html.escape(desc)}">
<meta name="twitter:image" content="{url}share.png?v={version}">
<style>:root{{color-scheme:only light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}body{{margin:0}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
</head>
<body>
"""
os.makedirs("public", exist_ok=True)
open("public/index.html", "w").write(head + page + "\n</body>\n</html>\n")
open("public/.nojekyll", "w").write("")
print(f"public/index.html {os.path.getsize('public/index.html')/1024:.0f} KB  (share image v={version})")

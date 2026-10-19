"""Build the three pages from site/template.html:
  build/index.html     Senate forecast
  build/governor.html  Governor forecast
  build/early.html     Early voting (both races)
Each page gets its race's data and names. build_public.py wraps them for GitHub Pages."""
import json, os, sys
sys.path.insert(0, "pipeline")
from races import RACES

tpl = open("site/template.html").read()
paths = open("data/tx_paths.json").read()
for marker in ("/*__DATA__*/null", "/*__PATHS__*/null"):
    assert tpl.count(marker) == 1, f"template must contain {marker} exactly once"

PAGES = [  # (file, race whose data the page uses, page kind, title)
    ("index.html", "senate", "race", "Texas Senate Forecast"),
    ("governor.html", "governor", "race", "Texas Governor Forecast"),
    ("early.html", "senate", "early", "Texas Early Vote Tracker"),
]
os.makedirs("build", exist_ok=True)
for fname, key, kind, title in PAGES:
    race, data = RACES[key], open(f"site/data_{key}.json").read()
    h = race["history"]
    subs = {
        "__TITLE__": title, "__PAGE__": kind, "__PAGE_FILE__": "" if fname == "index.html" else fname,
        "__OFFICE_LC__": "Senate" if key == "senate" else "governor",
        "__D_FULL__": race["d_full"], "__R_FULL__": race["r_full"], "__D__": race["d"], "__R__": race["r"],
        "__DI__": race["d_init"], "__RI__": race["r_init"], "__HA_LABEL__": h[0]["label"], "__HB_LABEL__": h[1]["label"],
        "__CUR_SENATE__": 'aria-current="page"' if fname == "index.html" else "",
        "__CUR_GOVERNOR__": 'aria-current="page"' if fname == "governor.html" else "",
        "__CUR_EARLY__": 'aria-current="page"' if fname == "early.html" else "",
    }
    html = tpl.replace("/*__DATA__*/null", data).replace("/*__PATHS__*/null", paths)
    for k in sorted(subs, key=len, reverse=True):          # longest first: __D_FULL__ before __D__
        html = html.replace(k, subs[k])
    leftover = [t for t in ("__D__", "__R__", "__DI__", "__RI__", "__PAGE", "__CUR_", "__TITLE__") if t in html]
    assert not leftover, f"{fname}: unfilled placeholders {leftover}"
    open(f"build/{fname}", "w").write(html)
    print(f"build/{fname} {len(html)/1024:.0f} KB")

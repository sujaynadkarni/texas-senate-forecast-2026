"""Inject site/data.json and the county map into site/template.html -> build/index.html."""
import json, os
tpl = open("site/template.html").read()
data = open("site/data.json").read()
paths = open("data/tx_paths.json").read()
for marker in ("/*__DATA__*/null", "/*__PATHS__*/null"):
    assert tpl.count(marker) == 1, f"template must contain {marker} exactly once"
html = tpl.replace("/*__DATA__*/null", data).replace("/*__PATHS__*/null", paths)
os.makedirs("build", exist_ok=True)
open("build/index.html", "w").write(html)
print(f"build/index.html {len(html)/1024:.0f} KB")

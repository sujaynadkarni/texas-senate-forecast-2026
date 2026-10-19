"""Texas county outlines -> SVG path strings (run once). Source: us-atlas@3.0.1 counties-10m TopoJSON."""
import json, math
t = json.load(open("data/raw/counties-10m.json"))
sx, sy = t["transform"]["scale"]; tx, ty = t["transform"]["translate"]
arcs = []
for a in t["arcs"]:                       # delta-decode quantized arcs
    x = y = 0; pts = []
    for dx, dy in a:
        x += dx; y += dy; pts.append((x * sx + tx, y * sy + ty))
    arcs.append(pts)
def ring(idx):
    out = []
    for i in idx:
        pts = arcs[i] if i >= 0 else arcs[~i][::-1]
        out.extend(pts if not out else pts[1:])
    return out
LAT0 = 31.0; K = math.cos(math.radians(LAT0))
proj = lambda lon, lat: ((lon + 106.65) * K, (36.5 - lat))
geoms = [g for g in t["objects"]["counties"]["geometries"] if g["id"].startswith("48")]
allp = []
shapes = {}
for g in geoms:
    polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
    rings = [[proj(*p) for p in ring(r)] for poly in polys for r in poly]
    shapes[g["id"][2:]] = (g["properties"]["name"], rings)
    for r in rings: allp.extend(r)
minx = min(p[0] for p in allp); maxx = max(p[0] for p in allp); miny = min(p[1] for p in allp); maxy = max(p[1] for p in allp)
W = 1000; S = W / (maxx - minx); H = (maxy - miny) * S
out = {"viewBox": f"0 0 {W} {H:.0f}", "counties": {}}
for fips, (name, rings) in shapes.items():
    d = "".join("M" + "L".join(f"{(x-minx)*S:.1f},{(y-miny)*S:.1f}" for x, y in r) + "Z" for r in rings)
    out["counties"][fips] = {"name": name, "d": d}
json.dump(out, open("data/tx_paths.json", "w"), separators=(",", ":"))
print(len(out["counties"]), "counties", out["viewBox"], round(len(json.dumps(out)) / 1024), "KB")

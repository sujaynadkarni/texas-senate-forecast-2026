"""County-level 2026 primary turnout (US Senate race votes) from the Texas SOS results API."""
# Raw files downloaded with curl from .../api/s3/enr/election/countyInfo/{53814 Dem, 53813 Rep}
import json, base64, pandas as pd
def county_votes(path):
    d = json.load(open(path))
    j = json.loads(base64.b64decode(d["upload"]))
    rows = {}
    for cid, c in j.items():
        sen = [r for r in c["Races"].values() if r["N"].startswith("U. S. SENATOR")]
        rows[c["N"].title()] = {"votes": sen[0]["T"] if sen else 0,
                                "cands": {x["LN"]: x["V"] for x in sen[0]["C"].values()} if sen else {}}
    return rows
dem, rep = county_votes("data/raw/dem_primary26.json"), county_votes("data/raw/rep_primary26.json")
df = pd.DataFrame({"dem_primary26": {k: v["votes"] for k, v in dem.items()},
                   "rep_primary26": {k: v["votes"] for k, v in rep.items()},
                   "talarico_primary": {k: v["cands"].get("TALARICO", 0) for k, v in dem.items()},
                   "paxton_primary": {k: v["cands"].get("PAXTON", 0) for k, v in rep.items()}})
df.index.name = "county_upper"
df.to_csv("data/primaries_2026.csv")
print(len(df), "counties; Dem", df.dem_primary26.sum(), "Rep", df.rep_primary26.sum())
print(df.sort_values("dem_primary26", ascending=False).head(8))

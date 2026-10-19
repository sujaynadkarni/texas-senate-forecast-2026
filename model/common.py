"""Shared county data + region definitions."""
import pandas as pd, numpy as np

URBAN = ["Harris", "Dallas", "Bexar", "Travis"]
SUBURB = ["Tarrant", "Collin", "Denton", "Fort Bend", "Williamson", "Hays"]
OUTER = ["Montgomery", "Brazoria", "Galveston", "Comal", "Ellis", "Parker", "Johnson", "Kaufman",
         "Rockwall", "Guadalupe", "Bastrop", "Wise", "Hood", "Hunt", "Grayson", "Waller", "Liberty", "Chambers"]

def region(row):
    if row.county in URBAN: return "Urban core"
    if row.county in SUBURB: return "Big suburbs"
    if row.county in OUTER: return "Outer suburbs"
    if row.hisp_reg_pct24 >= 50: return "Hispanic South/West"
    if row.sen24_total >= 30000: return "Mid-size metros"
    return "Rural"

def load():
    c = pd.read_csv("data/counties.csv", dtype={"fips": str})
    for r in ["sen14", "pres16", "sen18", "gov18", "ag18", "sen20", "pres20", "gov22", "ag22", "sen24", "pres24"]:
        c[f"{r}_d2"] = c[f"{r}_D"] / (c[f"{r}_D"] + c[f"{r}_R"])          # Dem two-party share
    c["region"] = c.apply(region, axis=1)
    p = pd.read_csv("data/primaries_2026.csv")
    p["county"] = p.county_upper
    key = lambda s: s.str.upper().str.replace(r"[^A-Z]", "", regex=True)      # "La Salle" == "LASALLE"
    c = c.merge(p.drop(columns="county_upper"), left_on=key(c.county), right_on=key(p.county_upper), how="left")
    c = c.drop(columns=[x for x in ["key_0", "county_y"] if x in c]).rename(columns={"county_x": "county"})
    for y, f in (("18", "prim18"), ("22", "prim22")):
        tot = {}
        for party in "dr":
            d = pd.read_csv(f"data/raw/{party}{f}.csv", dtype={"CNTYVTD": str})
            d["fips"] = d.CNTYVTD.str[:3]
            tot[party] = d.groupby("fips")[[x for x in d.columns if x not in ("CNTYVTD", "VTDKEY", "fips")]].sum().sum(axis=1)
        c[f"dem_primary{y}"] = c.fips.map(tot["d"]).fillna(0)
        c[f"rep_primary{y}"] = c.fips.map(tot["r"]).fillna(0)
    for y in ("18", "22", "26"):
        c[f"dprim_share{y}"] = c[f"dem_primary{y}"] / (c[f"dem_primary{y}"] + c[f"rep_primary{y}"])
    return c

def statewide(c, share, votes):
    return (c[share] * c[votes]).sum() / c[votes].sum()

"""Aggregate Texas Legislative Council precinct (VTD) results to county level."""
import pandas as pd, re, os
RAW = "data/raw"
names = pd.read_csv(f"{RAW}/counties.txt", sep="|", dtype=str)
names["fips"] = names.COUNTYFP
names["county"] = names.COUNTYNAME.str.replace(" County", "", regex=False)
names = names[["fips", "county"]].set_index("fips")

races = {  # file -> (R candidate, D candidate)
    "sen14": ("Cornyn", "Alameel"), "pres16": ("Trump", "Clinton"),
    "sen18": ("Cruz", "O'Rourke"), "gov18": ("Abbott", "Valdez"), "ag18": ("Paxton", "Nelson"),
    "sen20": ("Cornyn", "Hegar"), "pres20": ("Trump", "Biden"),
    "gov22": ("Abbott", "O'Rourke"), "ag22": ("Paxton", "Garza"),
    "sen24": ("Cruz", "Allred"), "pres24": ("Trump", "Harris"),
}
out = names.copy()
for f, (r, d) in races.items():
    df = pd.read_csv(f"{RAW}/{f}.csv", dtype={"CNTYVTD": str})
    df["fips"] = df.CNTYVTD.str[:3]
    cols = [c for c in df.columns if c not in ("CNTYVTD", "VTDKEY", "fips")]
    g = df.groupby("fips")[cols].sum()
    rc = [c for c in cols if c.startswith(r + "R_")][0]
    dc = [c for c in cols if c.startswith(d + "D_")][0]
    out[f"{f}_R"] = g[rc]; out[f"{f}_D"] = g[dc]; out[f"{f}_total"] = g[cols].sum(axis=1)
for y in ("14", "16", "18", "20", "22", "24"):
    df = pd.read_csv(f"{RAW}/vote{y}.csv", dtype={"CNTYVTD": str})
    df["fips"] = df.CNTYVTD.str[:3]
    g = df.groupby("fips")[["Voter_Registration", "Turnout", "Spanish_Surname_Voter_Registration"]].sum()
    out[f"reg{y}"] = g.Voter_Registration; out[f"turnout{y}"] = g.Turnout
    out[f"hisp_reg_pct{y}"] = (g.Spanish_Surname_Voter_Registration / g.Voter_Registration * 100).round(1)
out = out.fillna(0)
out.to_csv("data/counties.csv")
print(len(out), "counties")
for f in races:
    R, D, T = out[f"{f}_R"].sum(), out[f"{f}_D"].sum(), out[f"{f}_total"].sum()
    print(f"{f:7s} R {R/T*100:5.2f}%  D {D/T*100:5.2f}%  margin R+{(R-D)/T*100:5.2f}  total {T:,.0f}")
for y in ("18", "20", "22", "24"):
    print(f"20{y} registered {out[f'reg{y}'].sum():,.0f} turnout {out[f'turnout{y}'].sum():,.0f}")

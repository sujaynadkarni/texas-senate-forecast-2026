"""Social preview cards (1200x630 PNG) shown when a page link is posted on X, Facebook, LinkedIn.
  public/share_senate.png, public/share_governor.png  one race, with the needle
  public/share_early.png                              both races side by side
Reads site/data_<race>.json. Run after export.py."""
import json, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Wedge, Circle

sys.path.insert(0, "pipeline")
from races import RACES, margin_label

INK, INK2 = "#121212", "#4d4d4d"
DEM, REP = "#1f63c4", "#cf3a30"
BANDS = [(0, .05, "#c9463c"), (.05, .25, "#e48c80"), (.25, .4, "#f3c6be"), (.4, .6, "#e8e0cf"),
         (.6, .75, "#b7cdec"), (.75, .95, "#6f9bd6"), (.95, 1, "#2d68bf")]


def canvas():
    fig = plt.figure(figsize=(12, 6.3), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1200); ax.set_ylim(0, 630); ax.axis("off")
    return fig, ax


def masthead(ax, title, d):
    updated = datetime.fromisoformat(d["generated"]).astimezone(ZoneInfo("America/Chicago")).strftime("%b %-d, %Y")
    live = d["mode"] in ("live", "final")
    ax.text(60, 572, title, fontsize=17, fontweight="bold", color=INK, va="center")
    ax.text(1140, 572, ("LIVE RESULTS · " if live else "") + f"UPDATED {updated.upper()}", fontsize=14,
            color=INK2, ha="right", va="center", fontweight="bold")
    ax.plot([60, 1140], [545, 545], color=INK, lw=2)


def gauge(ax, cx, cy, r0, r1, p, lw=5):
    for a, b, col in BANDS:
        ax.add_patch(Wedge((cx, cy), r1, 180 * a, 180 * b, width=r1 - r0, facecolor=col, edgecolor="white", lw=1.5))
    ang = np.pi * min(.995, max(.005, p))                    # p = Democrat's chance; 1 points left
    ax.plot([cx, cx + (r1 - 15) * np.cos(ang)], [cy, cy + (r1 - 15) * np.sin(ang)], color=INK, lw=lw, solid_capstyle="round")
    ax.add_patch(Circle((cx, cy), r0 * 0.11, color=INK)); ax.add_patch(Circle((cx, cy), r0 * 0.045, color="white"))


def race_card(key):
    d = json.load(open(f"site/data_{key}.json")); race = RACES[key]
    p = d["needle"]["p"]
    fig, ax = canvas()
    masthead(ax, f"TEXAS {race['office'].upper()} FORECAST", d)
    ax.text(60, 480, f"{race['d_full']} (D)", fontsize=22, color=DEM, fontweight="bold", va="center")
    ax.text(60, 400, f"{round(p * 100)}%", fontsize=78, color=DEM, fontweight="bold", va="center")
    ax.text(1140, 480, f"{race['r_full']} (R)", fontsize=22, color=REP, fontweight="bold", va="center", ha="right")
    ax.text(1140, 400, f"{round((1 - p) * 100)}%", fontsize=78, color=REP, fontweight="bold", va="center", ha="right")
    ax.text(60, 335, "chance of winning", fontsize=15, color=INK2, va="center")
    ax.text(1140, 335, "chance of winning", fontsize=15, color=INK2, va="center", ha="right")
    gauge(ax, 600, 120, 120, 205, p)
    label = "Estimated final margin" if d["mode"] in ("live", "final") else "Expected margin"
    ax.text(600, 62, f"{label}: {margin_label(key, (2 * d['needle']['median'] - 1) * 100, True)}", fontsize=21,
            color=INK, ha="center", va="center", fontweight="bold")
    ax.text(600, 26, "County map · polls · early vote · live needle on election night", fontsize=14, color=INK2, ha="center", va="center")
    fig.savefig(f"public/share_{key}.png", dpi=100, facecolor="white"); plt.close(fig)


def early_card():
    ds = {k: json.load(open(f"site/data_{k}.json")) for k in RACES}
    e = ds["senate"].get("early")
    fig, ax = canvas()
    masthead(ax, "TEXAS EARLY VOTE TRACKER", ds["senate"])
    if e:
        big = f"{e['total']:,}"
        sub = "mail ballots returned" if e["day"] == 0 else f"Texans have voted early · day {e['day']} of 12"
    else:
        big, sub = "–", "early voting starts Oct. 19"
    ax.text(600, 455, big, fontsize=72, color=INK, fontweight="bold", ha="center", va="center")
    ax.text(600, 385, sub, fontsize=20, color=INK2, ha="center", va="center")
    for i, (k, x) in enumerate((("senate", 330), ("governor", 870))):
        race, p = RACES[k], ds[k]["needle"]["p"]
        gauge(ax, x, 110, 80, 140, p, lw=4)
        ax.text(x, 300, race["office"], fontsize=18, color=INK, fontweight="bold", ha="center", va="center")
        ax.text(x - 245, 262, f"{race['d']} {round(p * 100)}%", fontsize=15, color=DEM, fontweight="bold", ha="left", va="center")
        ax.text(x + 245, 262, f"{race['r']} {round((1 - p) * 100)}%", fontsize=15, color=REP, fontweight="bold", ha="right", va="center")
    ax.text(600, 30, "County-by-county turnout vs. 2022 · forecasts for Senate and governor", fontsize=14, color=INK2, ha="center", va="center")
    fig.savefig("public/share_early.png", dpi=100, facecolor="white"); plt.close(fig)


def main():
    os.makedirs("public", exist_ok=True)
    for k in RACES:
        race_card(k)
    early_card()
    print("public/share_{" + ",".join(RACES) + ",early}.png")


if __name__ == "__main__":
    main()

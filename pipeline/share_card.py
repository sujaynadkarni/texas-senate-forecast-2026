"""Social preview card (1200x630 PNG) shown when the site link is posted on X, Facebook, LinkedIn.
Reads site/data.json, writes public/share.png. Run after export.py."""
import json, os
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Wedge, Circle

INK, INK2, RULE = "#121212", "#4d4d4d", "#dcdcdc"
DEM, REP = "#1f63c4", "#cf3a30"
BANDS = [(0, .05, "#c9463c"), (.05, .25, "#e48c80"), (.25, .4, "#f3c6be"), (.4, .6, "#e8e0cf"),
         (.6, .75, "#b7cdec"), (.75, .95, "#6f9bd6"), (.95, 1, "#2d68bf")]


def margin_label(share):
    m = (2 * share - 1) * 100
    return ("Talarico" if m >= 0 else "Paxton") + f" +{abs(m):.1f}"


def main():
    d = json.load(open("site/data.json"))
    n = d["needle"]
    p = n["p"]
    updated = datetime.fromisoformat(d["generated"]).astimezone(ZoneInfo("America/Chicago")).strftime("%b %-d, %Y")
    live = d["mode"] in ("live", "final")

    fig = plt.figure(figsize=(12, 6.3), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1200); ax.set_ylim(0, 630); ax.axis("off")

    ax.text(60, 572, "TEXAS SENATE FORECAST", fontsize=17, fontweight="bold", color=INK, va="center")
    ax.text(1140, 572, ("LIVE RESULTS · " if live else "") + f"UPDATED {updated.upper()}", fontsize=14,
            color=INK2, ha="right", va="center", fontweight="bold")
    ax.plot([60, 1140], [545, 545], color=INK, lw=2)

    ax.text(60, 480, "James Talarico (D)", fontsize=22, color=DEM, fontweight="bold", va="center")
    ax.text(60, 400, f"{round(p * 100)}%", fontsize=78, color=DEM, fontweight="bold", va="center")
    ax.text(1140, 480, "Ken Paxton (R)", fontsize=22, color=REP, fontweight="bold", va="center", ha="right")
    ax.text(1140, 400, f"{round((1 - p) * 100)}%", fontsize=78, color=REP, fontweight="bold", va="center", ha="right")
    ax.text(60, 335, "chance of winning", fontsize=15, color=INK2, va="center")
    ax.text(1140, 335, "chance of winning", fontsize=15, color=INK2, va="center", ha="right")

    # needle gauge: Talarico on the left, Paxton on the right (p=1 points left)
    cx, cy, r0, r1 = 600, 120, 120, 205
    for a, b, col in BANDS:
        ax.add_patch(Wedge((cx, cy), r1, 180 * a, 180 * b, width=r1 - r0, facecolor=col, edgecolor="white", lw=1.5))
    ang = np.pi * min(.995, max(.005, p))
    ax.plot([cx, cx + 190 * np.cos(ang)], [cy, cy + 190 * np.sin(ang)], color=INK, lw=5, solid_capstyle="round")
    ax.add_patch(Circle((cx, cy), 13, color=INK)); ax.add_patch(Circle((cx, cy), 5, color="white"))

    label = "Estimated final margin" if live else "Expected margin"
    ax.text(600, 62, f"{label}: {margin_label(n['median'])}", fontsize=21, color=INK, ha="center", va="center", fontweight="bold")
    ax.text(600, 26, "County map · polls · early vote · live needle on election night", fontsize=14, color=INK2,
            ha="center", va="center")

    os.makedirs("public", exist_ok=True)
    fig.savefig("public/share.png", dpi=100, facecolor="white")
    print("public/share.png")


if __name__ == "__main__":
    main()

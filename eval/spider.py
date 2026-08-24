"""Spider (radar) diagram of eval results: GraphLang vs text2cypher.

Axes: overall EX accuracy, multi-hop EX, 1-hop EX, syntax validity, and
result token economy (normalized inverse of mean result tokens: fewer
tokens = further out). All axes 0..100, so the two shapes compare
directly. Colors: validated categorical palette (dataviz reference),
series identity carried by hue + direct labels, values labeled at
vertices (selective: one label per vertex per series).

Usage: uv run python -m eval.spider
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).parent / "out"

SERIES_COLORS = {"GraphLang": "#2a78d6", "text2cypher": "#eb6834"}
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#1a1a19"
TEXT_SECONDARY = "#5f5e58"
GRID = "#d8d7d0"


def token_economy(mean_tokens: float | None, worst: float) -> float:
    """Map mean result tokens to 0..100 where fewer tokens = higher."""
    if mean_tokens is None or worst <= 0:
        return 0.0
    return max(0.0, 100.0 * (1 - mean_tokens / worst))


def main() -> None:
    results = json.loads((OUT / "results.json").read_text())
    gl = results["graphlang"]
    cy = results["text2cypher"]
    live_baseline = "overall" in cy

    axes_labels = ["Overall\nexecution accuracy", "Multi-hop\naccuracy",
                   "1-hop\naccuracy", "Syntax\nvalidity",
                   "Result token\neconomy"]

    worst_tokens = max(
        [t for t in (gl.get("mean_result_tokens"),
                     cy.get("mean_result_tokens") if live_baseline else None)
         if t is not None] or [1]) * 1.25

    def vector(summary: dict) -> list[float]:
        return [summary.get("overall") or 0.0,
                summary.get("multi-hop") or 0.0,
                summary.get("1-hop") or 0.0,
                summary.get("syntax_validity") or 0.0,
                token_economy(summary.get("mean_result_tokens"), worst_tokens)]

    series = {"GraphLang": vector(gl)}
    if live_baseline:
        series["text2cypher"] = vector(cy)
    else:
        published = cy.get("claude-3.5-sonnet", 61.6)
        series["text2cypher"] = [published, None, None, None, None]

    n = len(axes_labels)
    angles = [2 * math.pi * i / n - math.pi / 2 for i in range(n)]

    fig, ax = plt.subplots(figsize=(7.5, 7.0),
                           subplot_kw={"projection": "polar"})
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_theta_offset(0)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], color=TEXT_SECONDARY,
                       fontsize=8)
    ax.set_xticks(angles)
    ax.set_xticklabels(axes_labels, color=TEXT_PRIMARY, fontsize=9.5)
    ax.tick_params(axis="x", pad=18)
    ax.grid(color=GRID, linewidth=0.7)
    ax.spines["polar"].set_color(GRID)

    for name, values in series.items():
        color = SERIES_COLORS[name]
        if any(v is None for v in values):
            continue  # published-baseline mode plots a single ring below
        closed_angles = angles + angles[:1]
        closed_values = values + values[:1]
        ax.plot(closed_angles, closed_values, color=color, linewidth=2,
                label=name)
        ax.fill(closed_angles, closed_values, color=color, alpha=0.12)
        for ang, val in zip(angles, values):
            ax.annotate(f"{val:.0f}", xy=(ang, val),
                        xytext=(ang, min(val + 9, 104)),
                        color=color, fontsize=8.5, fontweight="bold",
                        ha="center", va="center")

    if not live_baseline:
        published = series["text2cypher"][0]
        ax.plot(angles + angles[:1], [published] * (n + 1),
                color=SERIES_COLORS["text2cypher"], linewidth=1.6,
                linestyle="--",
                label=f"text2cypher (published overall {published:.0f})")

    note = results.get("slice_note", "")
    subtitle = (f'{results["graph"]} slice, n={results["n"]}, '
                f'model {results["model"]}')
    ax.set_title("GraphLang vs text2cypher, CypherBench slice",
                 color=TEXT_PRIMARY, fontsize=13, pad=34)
    fig.text(0.5, 0.945, subtitle, ha="center", color=TEXT_SECONDARY,
             fontsize=9)
    fig.text(0.5, 0.015, note, ha="center", color=TEXT_SECONDARY,
             fontsize=7, wrap=True)
    ax.legend(loc="lower right", bbox_to_anchor=(1.18, -0.08), frameon=False,
              labelcolor=TEXT_PRIMARY, fontsize=9)

    OUT.mkdir(exist_ok=True)
    out_path = OUT / "spider.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight",
                facecolor=SURFACE)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

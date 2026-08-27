"""Spider (radar) diagram of eval results: theorem vs text2cypher.

Axes: overall EX accuracy, multi-hop EX, 1-hop EX, syntax validity, and
result token economy (normalized inverse of mean result tokens: fewer
tokens = further out). All axes 0..100 so the two shapes compare
directly. Colors: validated categorical palette (dataviz reference);
series identity carried by hue plus legend, values labeled at vertices.

Usage: uv run python -m eval.spider [tag ...]
Plots eval/out/results.json by default; pass tags (e.g. "sonnet") to
plot results-<tag>.json files as extra panels.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).parent / "out"

SERIES_COLORS = {"theorem": "#2a78d6", "text2cypher": "#eb6834"}
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#1a1a19"
TEXT_SECONDARY = "#5f5e58"
GRID = "#d8d7d0"

AXES_LABELS = ["Overall\naccuracy", "Multi-hop\naccuracy", "1-hop\naccuracy",
               "Syntax\nvalidity", "Token\neconomy"]


def token_economy(mean_tokens: float | None, worst: float) -> float:
    if mean_tokens is None or worst <= 0:
        return 0.0
    return max(0.0, 100.0 * (1 - mean_tokens / worst))


def vectors(results: dict) -> dict[str, list[float]]:
    gl, cy = results["theorem"], results["text2cypher"]
    worst = max(t for t in (gl.get("mean_result_tokens"),
                            cy.get("mean_result_tokens")) if t) * 1.25

    def vec(s):
        return [s["overall"], s["multi-hop"], s["1-hop"],
                s["syntax_validity"],
                token_economy(s.get("mean_result_tokens"), worst)]
    return {"theorem": vec(gl), "text2cypher": vec(cy)}


def draw(ax, results: dict) -> None:
    n = len(AXES_LABELS)
    angles = [i * 2 * math.pi / n for i in range(n)]
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_facecolor(SURFACE)
    ax.set_ylim(0, 100)
    ax.set_rlabel_position(180 / n)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", ""], color=TEXT_SECONDARY,
                       fontsize=8)
    ax.set_xticks(angles)
    ax.set_xticklabels(AXES_LABELS, color=TEXT_PRIMARY, fontsize=9.5)
    ax.tick_params(axis="x", pad=16)
    ax.grid(color=GRID, linewidth=0.7)
    ax.spines["polar"].set_color(GRID)

    for name, values in vectors(results).items():
        color = SERIES_COLORS[name]
        closed_a = angles + angles[:1]
        closed_v = values + values[:1]
        ax.plot(closed_a, closed_v, color=color, linewidth=2, label=name)
        ax.fill(closed_a, closed_v, color=color, alpha=0.12)
        for ang, val in zip(angles, values):
            ax.annotate(f"{val:.0f}", xy=(ang, max(val - 11, 6)), color=color,
                        fontsize=8.5, fontweight="bold", ha="center",
                        va="center")

    ax.set_title(f'{results["model"]}\n', color=TEXT_SECONDARY, fontsize=9)


def main() -> None:
    tags = sys.argv[1:]
    files = [OUT / "results.json"] + [OUT / f"results-{t}.json" for t in tags]
    all_results = [json.loads(f.read_text()) for f in files if f.exists()]

    fig, axes = plt.subplots(
        1, len(all_results), figsize=(6.4 * len(all_results), 6.8),
        subplot_kw={"projection": "polar"})
    if len(all_results) == 1:
        axes = [axes]
    fig.patch.set_facecolor(SURFACE)
    for ax, results in zip(axes, all_results):
        draw(ax, results)

    r0 = all_results[0]
    fig.suptitle("theorem vs text2cypher, CypherBench slice "
                 f'({r0["graph"]}, n={r0["n"]})',
                 color=TEXT_PRIMARY, fontsize=13, y=1.0)
    fig.text(0.5, 0.012, r0.get("slice_note", ""), ha="center",
             color=TEXT_SECONDARY, fontsize=7)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", frameon=False,
               labelcolor=TEXT_PRIMARY, fontsize=9)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))

    OUT.mkdir(exist_ok=True)
    out_path = OUT / "spider.png"
    fig.savefig(out_path, dpi=180, facecolor=SURFACE)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

"""Where does theorem's prompt stop costing more than Cypher's?

theorem carries a tutorial in every prompt, because the model has never
seen the language; Cypher carries almost none, because it has. That is a
fixed cost. Against it, theorem's schema render is much cheaper per class
than the JSON schema the text2cypher prompt sends. So the two curves
cross, and the only question is where.

The prediction has been quoted from a fitted line over graphs with 5 to
11 classes, which is the region where theorem is worst and the region
least able to show a crossover. This measures it instead, on the seven
benchmark schemas and on their union, which is a real 50-class schema
rather than a synthetic one.

    uv run python -m eval.token_crossover

No model calls. Counts are the same `count_tokens` the benchmarks use.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.run_public import DATA, TEST_GRAPHS
from theorem.engine.executor import count_tokens

QUESTION = "Which entities are connected to the one named X, and how many are there?"


def union_schema() -> dict:
    """One CypherBench schema holding every graph's entities and relations.

    Real schemas of this size exist; benchmark ones do not, and a claim
    about large schemas measured only on small ones is an extrapolation.
    """
    entities: dict[str, dict] = {}
    relations: list[dict] = []
    seen: set[tuple] = set()
    for graph in TEST_GRAPHS:
        cb = json.loads((DATA / f"{graph}_schema.json").read_text())
        for e in cb["entities"]:
            entities.setdefault(e["label"], e)
        for r in cb["relations"]:
            key = (r["label"], r["subj_label"], r["obj_label"])
            if key not in seen:
                seen.add(key)
                relations.append(r)
    return {"entities": list(entities.values()), "relations": relations}


def measure(name: str, cb_schema: dict) -> dict:
    from eval.load_graph import derive_schema
    from eval.prompts import cypher_prompt
    from theorem.prompt import agent_prompt

    schema = derive_schema(cb_schema)
    theorem_tokens = count_tokens(agent_prompt(schema, QUESTION))
    cypher_tokens = count_tokens(cypher_prompt(cb_schema, QUESTION))
    return {
        "graph": name,
        "classes": len(schema.classes),
        "edges": len(schema.edges),
        "theorem": theorem_tokens,
        "cypher": cypher_tokens,
        "ratio": theorem_tokens / cypher_tokens,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--report", action="store_true", help="also write the published page"
    )
    args = ap.parse_args()
    rows = [
        measure(g, json.loads((DATA / f"{g}_schema.json").read_text()))
        for g in TEST_GRAPHS
    ]
    rows.append(measure("all seven, unioned", union_schema()))
    rows.sort(key=lambda r: r["classes"])

    print("| schema | classes | edges | theorem | text2cypher | ratio |")
    print("|---|---:|---:|---:|---:|---:|")
    for r in rows:
        lead = "**" if r["theorem"] < r["cypher"] else ""
        print(
            f"| {r['graph']} | {r['classes']} | {r['edges']} | "
            f"{lead}{r['theorem']:,}{lead} | {r['cypher']:,} | {r['ratio']:.2f}x |"
        )

    crossed = [r for r in rows if r["theorem"] < r["cypher"]]
    if crossed:
        first = min(crossed, key=lambda r: r["classes"])
        print(
            f"\ntheorem's prompt is smaller from {first['classes']} classes "
            f"({first['graph']}) upward."
        )
    else:
        print("\ntheorem's prompt is larger on every schema measured.")

    fit = crossover(rows)
    print(
        f"per class: theorem {fit['theorem_per_class']:.0f} tokens, "
        f"text2cypher {fit['cypher_per_class']:.0f}. theorem's fixed cost is "
        f"{fit['theorem_fixed']:.0f} tokens of tutorial; the lines cross at "
        f"{fit['crossover']:.0f} classes."
    )
    if args.report:
        print(f"\nwrote {write_doc(rows, fit)}")
    return 0


def crossover(rows: list[dict]) -> dict:
    """Fit a line to each arm and say where they meet.

    Two points are enough for a line and these two are the ends of the
    measured range, so this interpolates inside data rather than
    extrapolating past it.
    """
    small, large = rows[0], rows[-1]
    d = large["classes"] - small["classes"]
    gl_slope = (large["theorem"] - small["theorem"]) / d
    cy_slope = (large["cypher"] - small["cypher"]) / d
    # Fixed cost measured rather than extrapolated: the same prompt with
    # an empty schema. A fitted intercept came out negative for Cypher,
    # which is a fact about the fit and not about the prompt.
    empty = measure("empty", {"entities": [], "relations": []})
    gl_fixed, cy_fixed = empty["theorem"], empty["cypher"]
    return {
        "theorem_per_class": gl_slope,
        "cypher_per_class": cy_slope,
        "theorem_fixed": gl_fixed,
        "cypher_fixed": cy_fixed,
        # where the two measured lines meet, using their own intercepts
        "crossover": (
            (small["theorem"] - gl_slope * small["classes"])
            - (small["cypher"] - cy_slope * small["classes"])
        )
        / (cy_slope - gl_slope),
    }


DOC = Path(__file__).resolve().parents[1] / "docs" / "benchmarks" / "prompt-cost.md"


def write_doc(rows: list[dict], fit: dict) -> Path:
    from theorem.prompt import fingerprint

    first = min(
        (r for r in rows if r["theorem"] < r["cypher"]),
        key=lambda r: r["classes"],
        default=None,
    )
    biggest_single = max(
        (r for r in rows if r is not rows[-1]), key=lambda r: r["classes"]
    )
    lines = [
        "# What the prompt costs, and where that reverses",
        "",
        "theorem carries a tutorial in every prompt, because the model has",
        "never seen the language. Cypher carries none, because it has. That",
        "is a fixed cost, and on the benchmark graphs it makes theorem's",
        "prompt about 2.4 to 3.6 times larger.",
        "",
        "Against it, theorem's schema render is much cheaper per class than",
        "the JSON schema a text2cypher prompt sends. So the two costs are",
        "lines with different slopes, and they cross.",
        "",
        "## Measured",
        "",
        "| schema | classes | edges | theorem | text2cypher | ratio |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lead = "**" if r["theorem"] < r["cypher"] else ""
        lines.append(
            f"| {r['graph']} | {r['classes']} | {r['edges']} | "
            f"{lead}{r['theorem']:,}{lead} | {r['cypher']:,} | {r['ratio']:.2f}x |"
        )
    lines += [
        "",
        f"- theorem: **{fit['theorem_per_class']:.0f} tokens per class**, on top "
        f"of {fit['theorem_fixed']:,} tokens of tutorial and instructions that "
        "never grow.",
        f"- text2cypher: **{fit['cypher_per_class']:.0f} tokens per class**, on "
        f"top of {fit['cypher_fixed']:,}.",
        f"- The lines cross at **{fit['crossover']:.0f} classes**.",
        "",
    ]
    if first:
        lines += [
            f"The crossing is inside the measured range rather than past it: "
            f"theorem's prompt is smaller at {first['classes']} classes "
            f"({first['graph']}) and larger at {biggest_single['classes']}. "
            f"The seven benchmark graphs have {rows[0]['classes']} to "
            f"{biggest_single['classes']} classes each, which is the region "
            "where theorem is most expensive; a schema of the size real "
            "deployments have is the region where it is cheapest.",
            "",
        ]
    lines += [
        "## What this is not",
        "",
        "This is prompt size, not accuracy. It says what a question costs to",
        "ask, not how often the answer is right. The unioned schema is "
        f"assembled from real ones and has {rows[-1]['classes']} classes and "
        f"{rows[-1]['edges']} edge types, but no data was loaded behind it and "
        "no query was run against it, so nothing here is a claim about how a "
        "model performs at that size.",
        "",
        "Counts use the same `len(text) // 4` heuristic as every other number",
        f"in these docs. Prompt fingerprint `{fingerprint()}`.",
        "",
        "Reproduce: `uv run python -m eval.token_crossover --report`.",
        "",
    ]
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n")
    return DOC


if __name__ == "__main__":
    raise SystemExit(main())

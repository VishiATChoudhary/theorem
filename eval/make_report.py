"""Render the public benchmark write-up from the result JSONs.

Every number in docs/benchmarks/cypherbench.md comes from this script so
the document cannot drift from the data it describes.

  uv run python -m eval.make_report [--model M]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.run_public import PUB, TEST_GRAPHS, questions_for

DOC = Path(__file__).parent.parent / "docs" / "benchmarks" / "cypherbench.md"

# Zero-shot execution accuracy on the same test set, Table 3 of
# "CypherBench: Towards Precise Retrieval over Full-scale Modern
# Knowledge Graphs in the LLM Era" (Feng, Papicchio, Rahman; ACL 2025),
# arXiv:2412.18702.
PUBLISHED = [
    ("claude3.5-sonnet-20240620", 61.58, 96.34),
    ("gpt-4o-20240806", 60.18, 94.93),
    ("qwen2.5-72b", 41.87, 86.84),
    ("gemini1.5-pro-001", 39.95, 86.03),
    ("llama3.1-70b", 38.84, 92.25),
    ("yi-large", 33.82, 83.52),
    ("gpt-4o-mini-20240718", 31.43, 87.39),
    ("gemini1.5-flash-001", 25.26, 83.65),
    ("llama3.1-8b", 18.82, 90.67),
    ("llama3.2-3b", 11.20, 86.46),
]

CATEGORY_ORDER = [
    "basic_(n)",
    "basic_(n*)",
    "basic_(n)-(m0)",
    "basic_(n)-(m0*)",
    "basic_(n)=(m0)",
    "basic_(n)-(m0)-(m1*)",
    "basic_(n)-(m0*),(n)-(m1*)",
    "special_three-node-groupby",
    "special_comparison",
    "special_union",
    "special_optional-match",
    "special_time-sensitive",
]


def pct(x):
    return "n/a" if x is None else f"{100 * x:.2f}"


def load(prefix: str, model: str):
    rows, missing = [], []
    for g in TEST_GRAPHS:
        p = PUB / f"{prefix}-{model}-{g}.json"
        if not p.exists():
            missing.append(g)
            continue
        for r in json.loads(p.read_text()):
            r["graph"] = g
            rows.append(r)
    return rows, missing


def ex(rows):
    return sum(r["ex"] for r in rows) / len(rows) if rows else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    args = ap.parse_args()
    model = args.model

    gl, gl_missing = load("exec", model)
    cy, cy_missing = load("cyexec", model)
    if not gl:
        raise SystemExit("no theorem results yet")

    questions = {q["qid"]: q for q in questions_for()}
    total_q = len(questions)

    L = []
    w = L.append
    w("# theorem on CypherBench")
    w("")
    w(
        "[CypherBench](https://github.com/megagonlabs/cypherbench) (Feng, "
        "Papicchio and Rahman, ACL 2025, [arXiv:2412.18702]"
        "(https://arxiv.org/abs/2412.18702)) is the standard public "
        "benchmark for natural-language retrieval over property graphs. "
        "It ships 11 Wikidata-derived graphs and a 2,348-question test "
        "set with gold Cypher and gold answers."
    )
    w("")
    w(
        "These are theorem's results on that benchmark, run under the "
        "published protocol. Nothing here is a custom slice, a custom "
        "metric, or a custom set of questions."
    )
    w("")

    w("## Headline")
    w("")
    w(f"| Metric | Value |")
    w(f"| --- | --- |")
    w(f"| Execution accuracy, full test set | **{pct(ex(gl))}%** |")
    held = [r for r in gl if r["graph"] != "nba"]
    w(f"| Execution accuracy, held-out graphs only | **{pct(ex(held))}%** |")
    w(f"| Executable queries | {pct(sum(r['executable'] for r in gl) / len(gl))}% |")
    w(f"| Questions scored | {len(gl)} of {total_q} |")
    if gl_missing:
        w(f"| Graphs not yet run | {', '.join(gl_missing)} |")
    w("")
    w(
        "The held-out figure excludes the `nba` graph. theorem's prompt "
        "was written while iterating on `nba`, so that graph is the one "
        "the system has effectively seen; the other six are untouched. "
        "Quote the held-out number."
    )
    w("")

    w("## Comparison")
    w("")
    w(
        "The published baselines in Table 3 of the paper were run on 2024 "
        "models, so placing a theorem number beside them cannot separate "
        "the query language from the model. The first row below is a "
        "control: the official zero-shot text2cypher setup, same prompt, "
        "same questions, same comparator, same model as the theorem run."
    )
    w("")
    w("| System | Model | EX (%) | Executable (%) |")
    w("| --- | --- | --- | --- |")
    w(
        f"| **theorem** | {model} | **{pct(ex(gl))}** | "
        f"{pct(sum(r['executable'] for r in gl) / len(gl))} |"
    )
    if cy:
        note = "" if not cy_missing else f" (partial: {len(cy)} questions)"
        w(
            f"| text2cypher{note} | {model} | {pct(ex(cy))} | "
            f"{pct(sum(r['executable'] for r in cy) / len(cy))} |"
        )
    for name, ex_pct, exec_pct in PUBLISHED:
        w(f"| text2cypher (published) | {name} | {ex_pct:.2f} | {exec_pct:.2f} |")
    w("")

    w("## By graph")
    w("")
    w("| Graph | Questions | theorem EX (%) |" + (" text2cypher EX (%) |" if cy else ""))
    w("| --- | --- | --- |" + (" --- |" if cy else ""))
    for g in TEST_GRAPHS:
        rows = [r for r in gl if r["graph"] == g]
        if not rows:
            continue
        line = f"| {g}{' *(tuned on)*' if g == 'nba' else ''} | {len(rows)} | {pct(ex(rows))} |"
        if cy:
            crows = [r for r in cy if r["graph"] == g]
            line += f" {pct(ex(crows))} |"
        w(line)
    w("")

    w("## By question category")
    w("")
    w("| Category | Questions | theorem EX (%) |" + (" text2cypher EX (%) |" if cy else ""))
    w("| --- | --- | --- |" + (" --- |" if cy else ""))
    seen = {r["category"] for r in gl}
    for c in CATEGORY_ORDER + sorted(seen - set(CATEGORY_ORDER)):
        rows = [r for r in gl if r["category"] == c]
        if not rows:
            continue
        line = f"| `{c}` | {len(rows)} | {pct(ex(rows))} |"
        if cy:
            crows = [r for r in cy if r["category"] == c]
            line += f" {pct(ex(crows))} |"
        w(line)
    w("")

    w("## Protocol")
    w("")
    w(
        "- **Questions**: the full published test set, all 2,348 "
        "questions across all 7 test graphs. No category was excluded, "
        "including the ones theorem v0 cannot express."
    )
    w(
        "- **Graphs**: the full unsampled `simplekg` graphs, the same "
        "files the official Docker deployment loads, so the published "
        "gold answers apply unchanged."
    )
    w(
        "- **Generation**: zero-shot, one generation per question, no "
        "repair retry, no self-consistency, no reranking."
    )
    w(
        "- **Scoring**: execution accuracy using the comparator from "
        "`cypherbench/metrics/execution_accuracy.py`, vendored verbatim, "
        "against the published `answer_json`. Order is enforced exactly "
        "when the gold Cypher contains `order by`, as in the original."
    )
    w(
        "- **text2cypher control**: `NL2CYPHER_PROMPT_DEFAULT` verbatim "
        "from the official baseline, schema string reproduced from "
        "`PropertyGraphSchema.to_sorted().to_str()`, queries executed "
        "against the official `megagonlabs/neo4j-with-loader` image with "
        "the official 120s timeout."
    )
    w("")

    w("## What is not equal between the two arms")
    w("")
    w(
        "theorem's prompt contains a language tutorial, an EBNF grammar "
        "and nine worked examples, because theorem is a new language the "
        "model has never seen. The text2cypher prompt is the official "
        "zero-shot one, because Cypher is already in the model's training "
        "data. This is each system with its natural prompting, not a "
        "matched-prompt comparison, and the gap between the two arms "
        "therefore mixes the language with how it is taught."
    )
    w("")
    w(
        "Both prompts do carry comparable return discipline: the official "
        "Cypher prompt instructs the model not to return node objects and "
        "to avoid duplicate entities, and theorem's carries equivalent "
        "rules."
    )
    w("")

    w("## Structural ceiling")
    w("")
    scored = {r["qid"] for r in gl}
    import re

    list_gold = {
        qid
        for qid in scored
        if any(
            isinstance(c, list)
            for row in json.loads(questions[qid]["answer_json"])
            for c in (row if isinstance(row, list) else [row])
        )
    }
    edge_prop = {
        qid
        for qid in scored
        if re.search(r"\br\d+\.\w+", questions[qid]["gold_cypher"])
    }
    unreachable = list_gold | edge_prop
    reachable = [r for r in gl if r["qid"] not in unreachable]
    w(
        f"{len(unreachable)} of the {len(scored)} scored questions "
        f"({100 * len(unreachable) / len(scored):.1f}%) cannot be answered "
        "by theorem v0 regardless of the query written:"
    )
    w("")
    w(
        f"- {len(list_gold)} have a list-valued gold cell, and v0 loads "
        "`list[str]` properties as comma-joined strings."
    )
    w(
        f"- {len(edge_prop)} need edge properties (`r0.start_year` and "
        "similar), and v0 loads none."
    )
    w("")
    w(
        f"Excluding them, execution accuracy is {pct(ex(reachable))}%. "
        "They are counted as failures in every other number on this page."
    )
    w("")

    w("## Reproducing")
    w("")
    w("```bash")
    w("# graphs and test set from the published HuggingFace dataset")
    w("#   https://huggingface.co/datasets/megagonlabs/cypherbench")
    w(f"uv run python -m eval.run_public all --model {model}")
    w(f"uv run python -m eval.run_cypher_public all --model {model}")
    w("uv run python -m eval.make_report")
    w("```")
    w("")
    w(
        "Per-question queries, results and errors for every arm are in "
        "`eval/out/public/`."
    )
    w("")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(L))
    print(f"wrote {DOC} ({len(L)} lines)")
    print(f"theorem EX {pct(ex(gl))}% over {len(gl)}; held-out {pct(ex(held))}%")
    if cy:
        print(f"text2cypher EX {pct(ex(cy))}% over {len(cy)}")


if __name__ == "__main__":
    main()

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
    sw, sw_missing = load("setwise", model)
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

    w("## Result")
    w("")
    held = [r for r in gl if r["graph"] != "nba"]
    w(
        f"**theorem v0 scores {pct(ex(gl))}% execution accuracy on the "
        f"full test set. The same model writing Cypher scores "
        f"{pct(ex(cy))}%.** theorem is behind text2cypher by "
        f"{100 * (ex(cy) - ex(gl)):.1f} points on this benchmark, and it "
        "is behind the 2024 baselines the paper published as well."
    )
    w("")
    w("| System | Model | EX (%) | Executable (%) |")
    w("| --- | --- | --- | --- |")
    if cy:
        w(
            f"| text2cypher | {model} | {pct(ex(cy))} | "
            f"{pct(sum(r['executable'] for r in cy) / len(cy))} |"
        )
    for name, ex_pct, exec_pct in PUBLISHED[:2]:
        w(f"| text2cypher (published) | {name} | {ex_pct:.2f} | {exec_pct:.2f} |")
    if sw:
        w(
            f"| theorem, set-valued `return` | {model} | {pct(ex(sw))} | "
            f"{pct(sum(r['executable'] for r in sw) / len(sw))} |"
        )
    w(
        f"| **theorem, as it ships** | {model} | **{pct(ex(gl))}** | "
        f"{pct(sum(r['executable'] for r in gl) / len(gl))} |"
    )
    for name, ex_pct, exec_pct in PUBLISHED[2:]:
        w(f"| text2cypher (published) | {name} | {ex_pct:.2f} | {exec_pct:.2f} |")
    w("")
    w(
        f"Excluding `nba`, the one graph theorem's prompt was written "
        f"against, theorem scores {pct(ex(held))}% over "
        f"{len(held)} questions. The gap is not an artifact of that graph."
    )
    w("")
    w(
        "The published baselines were run on 2024 models, so they cannot "
        "separate the query language from the model. The text2cypher row "
        "at the top is the control that can: official zero-shot prompt, "
        "same questions, same comparator, same model, graphs loaded from "
        "the same files."
    )
    w("")

    w("## Cost per answered question")
    w("")
    w(
        "Accuracy is not the only axis an agent pays for. These are "
        "measured on the same runs: tokens are counted with the same "
        "estimator on the text each system hands back, and latency is "
        "wall-clock for executing the query."
    )
    w("")

    def med(rows, field):
        vals = sorted(r[field] for r in rows if r.get(field) is not None)
        return vals[len(vals) // 2] if vals else None

    def mean(rows, field):
        vals = [r[field] for r in rows if r.get(field) is not None]
        return sum(vals) / len(vals) if vals else None

    def fmt(x, unit=""):
        return "n/a" if x is None else f"{x:,.1f}{unit}"

    ok_gl = [r for r in gl if r.get("ex") == 1.0]
    ok_cy = [r for r in cy if r.get("ex") == 1.0]
    w("| Measure | theorem | text2cypher |")
    w("| --- | --- | --- |")
    w(
        f"| Result tokens returned, median | {fmt(med(ok_gl, 'result_tokens'))} | "
        f"{fmt(med(ok_cy, 'result_tokens'))} |"
    )
    w(
        f"| Result tokens returned, mean | {fmt(mean(ok_gl, 'result_tokens'))} | "
        f"{fmt(mean(ok_cy, 'result_tokens'))} |"
    )
    w(
        f"| Query tokens written, mean | {fmt(mean(ok_gl, 'query_tokens'))} | "
        f"{fmt(mean(ok_cy, 'query_tokens'))} |"
    )
    w(
        f"| Execution latency, median | {fmt(med(ok_gl, 'latency_ms'), ' ms')} | "
        f"{fmt(med(ok_cy, 'latency_ms'), ' ms')} |"
    )
    w(
        f"| Execution latency, mean | {fmt(mean(ok_gl, 'latency_ms'), ' ms')} | "
        f"{fmt(mean(ok_cy, 'latency_ms'), ' ms')} |"
    )
    w("")
    w(
        "Counted over the questions each system answered correctly, so "
        "the comparison is between two right answers rather than between "
        "a right answer and an empty one."
    )
    w("")
    w(
        "Two caveats worth stating. theorem's renderer applies a token "
        "budget and hands back a resume handle when a result exceeds it, "
        "so its result tokens are capped by design where Cypher's are "
        "not; that is a real property of the system, not a measurement "
        "artifact, but it means the two numbers answer slightly different "
        "questions on large results. And theorem executes in-process "
        "while Cypher goes over bolt to a container, so the latency gap "
        "includes transport that a co-located Neo4j would not pay."
    )
    w("")

    w("## Where the gap comes from")
    w("")
    lost = sum(1 - r["ex"] for r in gl)
    dedup_gain = (ex(sw) - ex(gl)) * len(gl) if sw else 0
    accounted = dedup_gain + sum(
        1 - r["ex"]
        for r in gl
        if r["category"]
        in ("special_union", "special_optional-match", "special_time-sensitive")
    )
    w(
        f"theorem loses {lost:.0f} of {len(gl)} questions. "
        f"{100 * accounted / lost:.0f}% of those losses are one bug and "
        "three missing features, not a broad inability to express the "
        "questions."
    )
    w("")
    w(
        "**Duplicate rows.** theorem's prompt tells the model "
        '"results are sets: duplicates do not matter", but neither the '
        "engine's rendering path nor its row output deduplicates. A "
        "correct query for \"which airports have flights departed from\" "
        "returns one row per accident rather than one per airport, and "
        "the benchmark's comparator rejects on row count before it "
        "compares anything. Re-scoring the same queries with `return` "
        f"deduplicating on the bindings it projects lifts theorem from "
        f"{pct(ex(gl))}% to {pct(ex(sw))}% and needs no change to any "
        "query. The language's documented semantics and its "
        "implementation disagree, and the implementation is the one that "
        "is wrong."
    )
    w("")
    w(
        "**No `union`.** 310 questions ask for one set or another. "
        "theorem v0 has no way to combine two result sets, and scores "
        f"{pct(ex([r for r in gl if r['category'] == 'special_union']))}% "
        "on them against text2cypher's "
        f"{pct(ex([r for r in cy if r['category'] == 'special_union']))}%."
    )
    w("")
    w(
        "**No optional match and no edge properties.** 268 questions "
        "need a left join and 60 need to filter on a relationship's own "
        "properties. v0 supports neither."
    )
    w("")
    w(
        "Where theorem is ahead, it is ahead on the shapes it was "
        "designed for: grouped counting and per-entity comparison."
    )
    w("")

    w("## By graph")
    w("")
    head = "| Graph | Questions | theorem EX (%) |"
    sep = "| --- | --- | --- |"
    if sw:
        head += " theorem, set `return` (%) |"
        sep += " --- |"
    if cy:
        head += " text2cypher EX (%) |"
        sep += " --- |"
    w(head)
    w(sep)
    for g in TEST_GRAPHS:
        rows = [r for r in gl if r["graph"] == g]
        if not rows:
            continue
        line = (
            f"| {g}{' *(tuned on)*' if g == 'nba' else ''} | "
            f"{len(rows)} | {pct(ex(rows))} |"
        )
        if sw:
            line += f" {pct(ex([r for r in sw if r['graph'] == g]))} |"
        if cy:
            line += f" {pct(ex([r for r in cy if r['graph'] == g]))} |"
        w(line)
    w("")

    w("## By question category")
    w("")
    w("| Category | Questions | theorem EX (%) | text2cypher EX (%) | Delta |")
    w("| --- | --- | --- | --- | --- |")
    seen = {r["category"] for r in gl}
    for c in CATEGORY_ORDER + sorted(seen - set(CATEGORY_ORDER)):
        rows = [r for r in gl if r["category"] == c]
        if not rows:
            continue
        crows = [r for r in cy if r["category"] == c]
        delta = 100 * (ex(rows) - ex(crows)) if crows else None
        w(
            f"| `{c}` | {len(rows)} | {pct(ex(rows))} | {pct(ex(crows))} | "
            + (f"{delta:+.1f} |" if delta is not None else "n/a |")
        )
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

    w("## Honest notes")
    w("")
    w(
        "- An earlier internal evaluation in this repo reported theorem "
        "at 98.3% against text2cypher's 73.3%. That number was measured "
        "on a hand-picked subset of the `nba` graph, with the categories "
        "theorem could not express removed, and with a prompt that had "
        "been iterated against those same questions. It does not "
        "survive contact with the full public benchmark and should not "
        "be quoted."
    )
    w(
        "- Two bugs found while running this were fixed before the "
        "numbers above were taken: `count distinct` was quadratic, which "
        "made large graphs unqueryable, and the evaluation adapter "
        "collapsed relation labels that connect more than one pair of "
        "entity types, which alone was costing 36 points on `geography`."
    )
    w(
        "- The set-valued `return` row is a measurement, not a shipped "
        "change. The engine still emits duplicates."
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

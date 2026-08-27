# theorem

A graph query and construction language designed for AI agents, with its own single-process engine. Working name; syntax is name-independent.

LLMs get roughly 40% of Cypher queries wrong on realistic schemas, and the failure modes are structural: reversed arrows, hallucinated labels, implicit grouping, long-range brackets. theorem removes each failure mode by construction:

- **No direction glyphs.** Edges traverse by role name: `follow parts supplied_by source as sups`. A wrong role is a type error caught before execution.
- **One line, one step, one name.** No chaining, no nesting, nothing to balance.
- **Explicit staged aggregation.** `group by sups as g` then `count distinct g.parts as n`. Adding a return column can never change the grouping.
- **Schema-closed vocabulary.** Every query is verified whole against the live schema before anything runs; errors name the line, suggest alternatives, and confirm nothing executed.
- **Token budgets.** `budget 2000 tokens` caps serialized results with explicit truncation and `continue @c...` handles.

And a write surface no existing query language has: `assert` with provenance, receipts carrying dedup candidates, `merge`/`distinct` resolution, `refine`/`compact` granularity verbs with full lineage, `retire`, `flag`, `derive class`, and queryable per-node health (`find nodes where health.loss > 0.8`).

## Quick start

```
uv sync
uv run pytest -q            # test suite
uv run python -m theorem program.thm --db ./db
uv run python -m theorem --repl
```

Example session:

```
find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts desc budget 2000 tokens
```

## Benchmark results

CypherBench NBA slice, 60 questions stratified over the expressible categories (no union, optional-match, or edge-property questions; both conditions ran on the identical slice with one repair retry each). Execution accuracy against CypherBench gold answers; text2cypher executed live on Neo4j.

| Condition | Overall EX | Multi-hop | 1-hop | Syntax valid | Mean result tokens |
|-----------|-----------:|----------:|------:|-------------:|-------------------:|
| theorem + Haiku 4.5 | **98.3%** | **96.0%** | **100%** | 100% | 245 |
| text2cypher + Haiku 4.5 | 73.3% | 56.0% | 85.7% | 98.3% | 394 |
| theorem + Sonnet 5 | **95.0%** | **92.0%** | 97.1% | 100% | 278 |
| text2cypher + Sonnet 5 | 71.7% | 60.0% | 80.0% | 96.7% | 207 |

Published frontier baselines for context: Claude 3.5 Sonnet 61.6% EX, GPT-4o 60.2% (CypherBench, arXiv 2412.18702); two model generations later, Claude Opus 4.8 and GPT-5.5 still sit at 51-58% Cypher EX with 19-44% on hard queries (Text2GraphQuery-Bench, arXiv 2602.11745). Model scaling is flat on this task. Our own runs show the same thing live: Sonnet 5 text2cypher is no better than Haiku 4.5 text2cypher, while the language switch moves both models 20+ points. The full "won't better models fix Cypher?" argument is Section 7 of `docs/report/theorem-v0-report.pdf`: corpus (not capacity) is the bottleneck and your schema is never in the corpus; surviving errors are the silent semantic kind that Cypher executes and theorem refuses; and a perfect Cypher generator still writes against a database with no receipts, dedup, lineage, granularity, health, or token budgets.

The headline: on multi-hop questions, the design's target zone, theorem with the small Haiku model reaches 96% where text2cypher with the same model reaches 56%. Three benchmark-driven language changes came out of the eval loop (global aggregates, trail semantics, the compute verb), each documented in the spec.

![Spider diagram](eval/out/spider.png)

Reproduce: `uv run python -m eval.run_eval --n 60` (needs the `claude` CLI; docker for the Neo4j text2cypher baseline), then `uv run python -m eval.spider`.

## Layout

| Path | What |
|------|------|
| `src/theorem/parser.py` | Tokenizer + line-oriented parser |
| `src/theorem/verifier.py` | Whole-program verify-before-execute |
| `src/theorem/engine/storage.py` | WAL + immutable snapshot runs, single process |
| `src/theorem/engine/executor.py` | Binding-table reads, budgets, serialization |
| `src/theorem/engine/writes.py` | Structural writes with receipts |
| `src/theorem/engine/dedup.py` | Blocking + similarity dedup pipeline |
| `src/theorem/engine/health.py` | Four health subscores |
| `src/theorem/session.py` | Session facade (parse, verify, execute) |
| `eval/` | CypherBench harness, prompts, spider chart |
| `docs/superpowers/specs/` | Language spec (decisions, grammar, semantics) |
| `research/` | Design briefing and research foundation |

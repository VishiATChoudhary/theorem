# GraphLang

A graph query and construction language designed for AI agents, with its own single-process engine. Working name; syntax is name-independent.

LLMs get roughly 40% of Cypher queries wrong on realistic schemas, and the failure modes are structural: reversed arrows, hallucinated labels, implicit grouping, long-range brackets. GraphLang removes each failure mode by construction:

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
uv run python -m graphlang program.gl --db ./db
uv run python -m graphlang --repl
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

See `eval/out/results.json` and the spider diagram at `eval/out/spider.png`. RESULTS_PLACEHOLDER

Reproduce: `uv run python -m eval.run_eval --n 60` (needs the `claude` CLI; docker for the Neo4j text2cypher baseline), then `uv run python -m eval.spider`.

## Layout

| Path | What |
|------|------|
| `src/graphlang/parser.py` | Tokenizer + line-oriented parser |
| `src/graphlang/verifier.py` | Whole-program verify-before-execute |
| `src/graphlang/engine/storage.py` | WAL + immutable snapshot runs, single process |
| `src/graphlang/engine/executor.py` | Binding-table reads, budgets, serialization |
| `src/graphlang/engine/writes.py` | Structural writes with receipts |
| `src/graphlang/engine/dedup.py` | Blocking + similarity dedup pipeline |
| `src/graphlang/engine/health.py` | Four health subscores |
| `src/graphlang/session.py` | Session facade (parse, verify, execute) |
| `eval/` | CypherBench harness, prompts, spider chart |
| `docs/superpowers/specs/` | Language spec (decisions, grammar, semantics) |
| `research/` | Design briefing and research foundation |

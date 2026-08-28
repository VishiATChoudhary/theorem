<p align="center">
  <img src="docs/assets/wordmark.svg" alt="theorem" width="340">
</p>

<p align="center"><b>A graph language agents can't get wrong.</b><br>
Every query is verified whole against the live schema before anything runs.</p>

<p align="center">
  <a href="https://github.com/VishiATChoudhary/theorem/actions/workflows/test.yml"><img src="https://github.com/VishiATChoudhary/theorem/actions/workflows/test.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/theorem/"><img src="https://img.shields.io/pypi/v/theorem" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-blue" alt="Python versions">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="License"></a>
</p>

---

LLMs get roughly **40% of Cypher queries wrong** on realistic schemas. Two model generations of scaling have not fixed it: frontier models still sit at 51-61% execution accuracy. The failure modes are structural: reversed arrows, hallucinated labels, implicit grouping, long-range brackets.

**theorem** removes each failure mode by construction. On CypherBench multi-hop questions, the small Haiku model writing theorem reaches **96%** where the same model writing Cypher reaches **56%**.

<p align="center">
  <img src="docs/assets/demo.gif" alt="theorem REPL: a typo is caught before execution with a suggestion; a five-step pipeline aggregates suppliers" width="720">
</p>

## Install

```bash
pip install theorem
```

Run a program or an interactive session:

```bash
theorem program.thm --db ./db
theorem --repl
```

## Sixty seconds of theorem

```
find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts desc budget 2000 tokens
```

One line, one step, one name. Reading it top to bottom is the whole mental model.

## Ingest anything

Any file, not just CSVs, lands as queryable graph nodes with page-level provenance: markdown, text, CSV, JSON/JSONL, PDFs, docx/xlsx/pptx, and images (stored with metadata) all normalize into document, chunk, table, and media nodes joined by `part_of` and traceable back to their source page. CSVs stay first-class and refinable as before. For domain-specific schemas, a playbook is a markdown file describing a use case in prose; any agent CLI compiles it into verified `derive class`/`derive edge` statements with lineage back to the playbook.

```bash
pip install "theorem[pdf,office]"
theorem ingest report.pdf --db ./db
theorem playbook compile playbook.md --db ./db --agent claude
```

## Why agents stop failing

- **No direction glyphs.** Edges traverse by role name: `follow parts supplied_by source as sups`. A wrong role is a type error caught before execution, not a silently empty result.
- **One line, one step, one name.** No chaining, no nesting, nothing to balance.
- **Explicit staged aggregation.** `group by sups as g`, then `count distinct g.parts as n`. Adding a return column can never change the grouping.
- **Schema-closed vocabulary.** Every query is verified whole against the live schema before anything runs; errors name the line, suggest the fix, and confirm nothing executed.
- **Token budgets.** `budget 2000 tokens` caps serialized results with explicit truncation and `continue @c...` handles.

And a write surface no existing query language has: `assert` with provenance, receipts carrying dedup candidates, `merge`/`distinct` resolution, `refine`/`compact` granularity verbs with full lineage, `retire`, `flag`, `derive class`, and queryable per-node health (`find nodes where health.loss > 0.8`).

## Benchmarks

CypherBench NBA slice, 60 questions stratified over the expressible categories; both conditions ran on the identical slice with one repair retry each. Execution accuracy against CypherBench gold answers; text2cypher executed live on Neo4j.

| Condition | Overall EX | Multi-hop | 1-hop | Syntax valid | Mean result tokens |
|-----------|-----------:|----------:|------:|-------------:|-------------------:|
| theorem + Haiku 4.5 | **98.3%** | **96.0%** | **100%** | 100% | 245 |
| text2cypher + Haiku 4.5 | 73.3% | 56.0% | 85.7% | 98.3% | 394 |
| theorem + Sonnet 5 | **95.0%** | **92.0%** | 97.1% | 100% | 278 |
| text2cypher + Sonnet 5 | 71.7% | 60.0% | 80.0% | 96.7% | 207 |

![Spider diagram](eval/out/spider.png)

Published frontier baselines for context: Claude 3.5 Sonnet 61.6% EX, GPT-4o 60.2% (CypherBench, arXiv 2412.18702); two model generations later, Claude Opus 4.8 and GPT-5.5 still sit at 51-58% Cypher EX with 19-44% on hard queries (Text2GraphQuery-Bench, arXiv 2602.11745). Model scaling is flat on this task; the language switch moves both models 20+ points. The full "won't better models fix Cypher?" argument is Section 7 of [the technical report](docs/report/graphlang-v0-report.pdf): corpus (not capacity) is the bottleneck and your schema is never in the corpus; surviving errors are the silent semantic kind that Cypher executes and theorem refuses; and a perfect Cypher generator still writes against a database with no receipts, dedup, lineage, granularity, health, or token budgets.

Reproduce: `uv run python -m eval.run_eval --n 60` (needs the `claude` CLI; docker for the Neo4j text2cypher baseline), then `uv run python -m eval.spider`.

## Development

```bash
git clone https://github.com/VishiATChoudhary/theorem
cd theorem
uv sync
uv run pytest -q     # 146 tests incl. property-based hardening, < 2s
```

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

## Community

theorem is a community project under Apache-2.0. The language grows spec-first: proposals are discussed as issues before syntax lands ([how it works](CONTRIBUTING.md)).

- [CONTRIBUTING.md](CONTRIBUTING.md): setup, test loop, DCO sign-off
- [ROADMAP.md](ROADMAP.md): union, optional traversal, edge properties are the next expressiveness targets
- [Good first issues](https://github.com/VishiATChoudhary/theorem/labels/good%20first%20issue)

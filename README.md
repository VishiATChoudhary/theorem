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

**theorem** removes each failure mode by construction. On the full public CypherBench test set, all 2,348 questions, the small Haiku model writing theorem reaches **78.0%** execution accuracy where the same model writing Cypher reaches **70.4%**, ahead on all seven graphs.

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

The complete public [CypherBench](https://github.com/megagonlabs/cypherbench) test set (ACL 2025): all 2,348 questions across all 7 test graphs, every match category, the full unsampled graphs, zero-shot with one generation and no repair retry, scored with the benchmark's own execution-accuracy comparator against its published answers.

| Condition | EX | Multi-hop EX | Executable | Mean result tokens |
|-----------|---:|-------------:|-----------:|-------------------:|
| theorem + Haiku 4.5 | **78.0%** | **78.7%** | 97.4% | **159** |
| text2cypher + Haiku 4.5 | 70.4% | 68.9% | 95.3% | 242 |
| text2cypher + Claude 3.5 Sonnet (published) | 61.6% | — | 96.3% | — |
| text2cypher + GPT-4o (published) | 60.2% | — | 94.9% | — |

The text2cypher row is a control, not a citation: same model, same questions, same comparator, the official zero-shot prompt, executed on the official Neo4j image. Excluding `nba`, the one graph theorem's prompt was written against, theorem scores 76.9%. Median execution latency is 0.2 ms against 67 ms over Bolt.

Full method, per-category results and the caveats that matter, including the prompt asymmetry between the two arms, are in [docs/benchmarks/cypherbench.md](docs/benchmarks/cypherbench.md). That benchmark measures one-shot translation; for convergence under retry and tokens across a whole agent loop, on graphs nothing was tuned on, see [docs/benchmarks/agent-loop.md](docs/benchmarks/agent-loop.md). Per-question queries and errors for both arms are in `eval/out/public/`.

Reproduce (needs the `claude` CLI, and docker for the text2cypher control):

```bash
uv run python -m eval.run_public all --model claude-haiku-4-5-20251001
uv run python -m eval.run_cypher_public all --model claude-haiku-4-5-20251001
uv run python -m eval.make_report
```

## Development

```bash
git clone https://github.com/VishiATChoudhary/theorem
cd theorem
uv sync
uv run pytest -q     # 277 tests incl. property-based hardening
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

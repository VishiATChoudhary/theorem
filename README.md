<p align="center">
  <img src="https://raw.githubusercontent.com/VishiATChoudhary/theorem/main/docs/assets/wordmark.svg" alt="theorem" width="340">
</p>

<p align="center"><b>A graph language agents can't get wrong.</b><br>
Every query is verified whole against the live schema before anything runs.</p>

<p align="center">
  <a href="https://vishiatchoudhary.github.io/theorem/">Documentation</a> &middot;
  <a href="https://vishiatchoudhary.github.io/theorem/tutorial/">Tutorial</a> &middot;
  <a href="https://vishiatchoudhary.github.io/theorem/using-theorem/">Use it in a project</a> &middot;
  <a href="https://vishiatchoudhary.github.io/theorem/benchmarks/">Benchmarks</a>
</p>

<p align="center">
  <a href="https://github.com/VishiATChoudhary/theorem/actions/workflows/test.yml"><img src="https://github.com/VishiATChoudhary/theorem/actions/workflows/test.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-blue" alt="Python versions">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="License"></a>
</p>

---

LLMs get roughly **40% of Cypher queries wrong** on realistic schemas. Two model generations of scaling have not fixed it: frontier models still sit at 51-61% execution accuracy. The failure modes are structural: reversed arrows, hallucinated labels, implicit grouping, long-range brackets.

**theorem** removes each failure mode by construction. On the full public CypherBench test set, all 2,348 questions, the small Haiku model writing theorem reaches **78.0%** execution accuracy where the same model writing Cypher reaches **70.4%**, ahead on all seven graphs.

<p align="center">
  <img src="https://raw.githubusercontent.com/VishiATChoudhary/theorem/main/docs/assets/demo.gif" alt="theorem REPL: a typo is caught before execution with a suggestion; a five-step pipeline aggregates suppliers" width="720">
</p>

## Install

Not on PyPI yet. Install from the repository, pinning a commit if you want
the language and the storage format to hold still:

```bash
pip install "git+https://github.com/VishiATChoudhary/theorem.git@main"
```

The core package has no dependencies. On PyPI the distribution is named
**`theoremql`**, because PyPI prohibits `theorem`; the module you import
and the command you run are `theorem` either way.

Run a program or an interactive session:

```bash
theorem program.thm --db ./db
theorem --repl
```

Or embed it, and let a model write the queries:

```python
from theorem import Schema, Session, answer

with Session("./db", Schema()) as db:
    db.execute("derive class supplier from entity with {country: str}")
    got = answer(db, "Which suppliers are in Germany?", your_model)
    print(got.rows, got.turns, got.errors)
```

`answer` is the loop the benchmarks measure: write, run, and on an error hand the error back verbatim and try again. Nothing is ever partly applied, so a repair is a fresh attempt rather than a cleanup.

Use `execute` (raises) and `rows` (raises, reads only) from your own code, and
`run` (renders the error as text) when a model is the caller. Getting that choice
right is the whole of [Using theorem in a project](docs/using-theorem.md), which
also covers schemas, locking, bulk loading and query limits.

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
pip install "theoremql[pdf,office] @ git+https://github.com/VishiATChoudhary/theorem.git@main"
theorem ingest report.pdf --db ./db
theorem playbook compile playbook.md --db ./db --agent claude
```

For data whose columns you already know, skip the model entirely:

```bash
theorem load parts.csv --db ./db --class part
theorem load links.csv --db ./db --edge supplied_by --role item=part --role source=supplier
theorem stats --db ./db
```

`--role` maps a role to the **column** naming the node that fills it, so
`links.csv` there has columns `part` and `supplier`. A program that fails
exits non-zero, so `theorem build.thm --db ./db && deploy` does what it looks
like it does.

## Why agents stop failing

- **No direction glyphs.** Edges traverse by role name: `follow parts supplied_by source as sups`. A wrong role is a type error caught before execution, not a silently empty result, except where an edge's two roles hold the same class and no schema check can distinguish them. That exception is [6.1% of our own broken queries](docs/benchmarks/silent-failure.md), and it is the honest ceiling on the headline of this README.
- **One line, one step, one name.** No chaining, no nesting, nothing to balance.
- **Explicit staged aggregation.** `group by sups as g`, then `count distinct g.parts as n`. Adding a return column can never change the grouping.
- **Schema-closed vocabulary.** Every query is verified whole against the live schema before anything runs; errors name the line, suggest the fix, and confirm nothing executed.
- **Token budgets.** `budget 2000 tokens` caps serialized results with explicit truncation and `continue @c...` handles.

And a write surface no existing query language has: `assert` with provenance, receipts carrying dedup candidates, `merge`/`distinct` resolution, `refine`/`compact` granularity verbs with full lineage, `retire`, `flag`, `derive class`, and queryable per-node health (`find nodes where health.loss > 0.8`).

## Benchmarks

The complete public [CypherBench](https://github.com/megagonlabs/cypherbench) test set (ACL 2025): all 2,348 questions across all 7 test graphs, every match category, the full unsampled graphs, zero-shot with one generation and no repair retry, scored with the benchmark's own execution-accuracy comparator against its published answers.

| Condition | EX | Multi-hop EX | Executable | Mean result tokens |
|-----------|---:|-------------:|-----------:|-------------------:|
| theorem + Haiku 4.5 | **78.0%** | **78.7%** | 96.6% | **167** |
| text2cypher + Haiku 4.5 | 70.4% | 69.6% | 95.3% | 242 |
| text2cypher + Claude 3.5 Sonnet (published) | 61.6% | — | 96.3% | — |
| text2cypher + GPT-4o (published) | 60.2% | — | 94.9% | — |

The text2cypher row is a control, not a citation: same model, same questions, same comparator, the official zero-shot prompt, executed on the official Neo4j image. Excluding `nba`, the one graph theorem's prompt was written against, theorem scores 76.9%. Median execution latency is 0.2 ms against 67 ms over Bolt.

theorem's prompt carries a tutorial the model has never seen, so it costs more per question on these graphs, which have 9 to 13 classes each. It costs 39 tokens per class against text2cypher's 85, and the lines cross at 31: on the seven schemas unioned, 40 classes, theorem's prompt is the smaller one ([prompt cost](docs/benchmarks/prompt-cost.md)).

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
uv run pytest -q     # unit, property-based, and end-to-end deployment tests
```

| Path | What |
|------|------|
| `src/theorem/parser.py` | Tokenizer + line-oriented parser |
| `src/theorem/verifier.py` | Whole-program verify-before-execute |
| `src/theorem/engine/storage.py` | WAL, automatic compaction, one-writer lock |
| `src/theorem/engine/executor.py` | Binding-table reads, budgets, serialization |
| `src/theorem/engine/writes.py` | Structural writes with receipts |
| `src/theorem/engine/dedup.py` | Blocking + similarity dedup pipeline |
| `src/theorem/engine/health.py` | Four health subscores |
| `src/theorem/session.py` | Session facade (parse, verify, execute, rows) |
| `src/theorem/prompt.py` | The prompt and agent loop the benchmarks measure |
| `src/theorem/ingest/bulk.py` | CSV/JSONL bulk load |
| `eval/` | CypherBench, agent-loop, frontier, broken-query and prompt-cost harnesses |
| `skills/theorem/` | The agent skill: how to use the language, for a model |
| `docs/language-spec.md` | Normative grammar and semantics |

## Community

theorem is a community project under Apache-2.0. The language grows spec-first: proposals are discussed as issues before syntax lands ([how it works](CONTRIBUTING.md)).

- [CHANGELOG.md](CHANGELOG.md): what changed in each release, and why
- [RELEASING.md](RELEASING.md): how a version is cut, and the PyPI setup that is still pending
- [CONTRIBUTING.md](CONTRIBUTING.md): setup, test loop, DCO sign-off
- [ROADMAP.md](ROADMAP.md): every open objective states the number that closes it
- [Good first issues](https://github.com/VishiATChoudhary/theorem/labels/good%20first%20issue)

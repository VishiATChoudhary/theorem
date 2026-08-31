---
name: theorem
description: "Use when building, querying, or reasoning over a graph of entities and relationships in Python, when a task needs a knowledge graph with provenance and lineage, or when an agent must write graph queries that fail loudly instead of returning a plausible empty answer. Covers the theorem language, its CLI, and its embedding API."
---

# theorem

A graph query and construction language whose whole program is verified
against the live schema before anything runs. A wrong class, edge,
property or role is a corrective error naming the line, not an empty
result that looks like an answer.

Reach for it when a task needs entities, relationships and questions over
both, and when being wrong loudly matters more than being terse.

## Do this first: get the language reference

**Do not write theorem from memory, and do not paraphrase the language
into your own summary.** The shipped tutorial is the exact text the
published benchmarks were measured against (prompt fingerprint
`eb0f4010`, about 1,250 tokens). Print it and follow it:

```bash
python -c "from theorem.prompt import TUTORIAL; print(TUTORIAL)"
```

Print the live schema too, since the vocabulary is closed and a class the
schema does not declare is an error:

```bash
python -c "
from theorem import Schema, Session
with Session('./mydb', Schema()) as db: print(db.run('schema'))"
```

If a question is being answered for a user rather than by you, prefer the
built-in loop, which is the one the benchmarks measure:

```python
from theorem import answer
got = answer(db, "Which suppliers are in Germany?", ask=your_model)
got.rows, got.query, got.turns, got.errors
```

## Install

Not on PyPI. The core package has no dependencies.

```bash
pip install "git+https://github.com/VishiATChoudhary/theorem.git@main"
theorem --help
```

Extras: `[pdf]` for PDF ingest, `[office]` for docx/xlsx/pptx. They name
the distribution, which is `theoremql` (PyPI prohibits `theorem`), while
the module and the command stay `theorem`:

```bash
pip install "theoremql[pdf] @ git+https://github.com/VishiATChoudhary/theorem.git@main"
```

## Pick the right call. This is the one thing to get right.

| call | on failure | takes |
|---|---|---|
| `session.execute(program)` | **raises** | reads and writes |
| `session.rows(program)` | **raises** | reads only, returns plain values |
| `session.run(program)` | **returns the error as text** | reads and writes |

`run` is the agent contract: it hands a model the corrective message
verbatim so the next turn can use it. **If you are writing Python, call
`execute` or `rows`.** Code that calls `run` and does not inspect the
returned string treats a refused program as a successful one, which is
the exact failure this language exists to prevent.

## The shape of a program

One line, one step, one name. No arrows, no nesting, no chaining.

```
find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts desc budget 2000 tokens
```

Edges traverse by **role name**, never by direction: `supplied_by(item:
part, source: supplier)` is entered by naming the role you want to arrive
at. Arriving at the role you already occupy is a type error.

## Starting a project

Derived classes are durable: they are rebuilt from lineage when the store
reopens, so declare them once rather than on every run.

```python
from theorem import Schema, Session

with Session("./mydb", Schema()) as db:
    if "supplier" not in db.schema.classes:
        db.execute("derive class supplier from entity with {country: str}")
        db.execute("derive class part from entity with {unit_cost: float}")
        db.execute("derive edge supplied_by(item: part, source: supplier)")
```

`Schema()` is the base (`entity` plus the document classes) and is what
the CLI opens by default. `Schema.supply_chain()` is the tutorial's demo
classes; use it only when following the tutorial.

## Loading data you already have

```bash
theorem load parts.csv --db ./mydb --class part
theorem load links.csv --db ./mydb --edge supplied_by \
    --role item=part --role source=supplier
theorem stats --db ./mydb
```

`--role` maps a role to the **column** naming the node that fills it, so
`links.csv` above has columns `part` and `supplier`, not `item` and
`source`. This is the single most common mistake with `load`.

Both loaders validate every row before writing any, so a bad file is
refused whole. For PDFs and anything whose structure is not already
known, `theorem ingest <file> --db ./mydb` stages it with page-level
provenance.

## From a shell

```bash
theorem build.thm --db ./mydb     # exits 1 if anything failed
theorem canonical query.thm       # one spelling; no database needed
theorem --repl --db ./mydb        # interactive; blank line runs a block
```

A failed program exits non-zero, so `theorem build.thm --db ./mydb &&
next-step` is safe. `canonical` exists because there is exactly one way
to write each operation, so two correct answers to the same question are
byte-identical: use it to compare queries rather than diffing the text a
model happened to emit.

## Reading an error

Errors are the interface, not an exception path. Each names the line,
suggests the fix, and states whether anything ran.

- `unknown class "suppler". did you mean: supplier?` The vocabulary is
  closed. Print the schema rather than guessing.
- `"p" is a part, which already occupies role "item"; to traverse
  supplied_by from part arrive at role "source"` You named the role you
  came from. Use the other one.
- `nothing was executed.` Verification is all or nothing, so retry the
  whole program. Without that line, some writes committed and the message
  says how many; retry the rest.
- `StoreLocked` Another process holds the directory. One writer at a
  time; readers are not blocked.

## Guardrails

- Bound anything a model authored: `with limits(seconds=5.0,
  max_rows=100_000):` around `db.rows(...)`. Defaults are 1,000,000 rows
  and 60 seconds.
- Use `budget N tokens` on `return` so a result cannot flood a context
  window. Truncation is explicit and hands back a `continue @c...` handle.
- Close the session, or use it as a context manager, so the lock is
  released promptly.

## What this language does not fix

A reversed role on an edge whose **two roles hold the same class** is
type-correct either way round, so no schema check can catch it. That is
6.1% of deliberately broken queries in the project's own audit. When you
declare such an edge, name its roles meaningfully (`child`/`father`, not
`subj`/`obj`) so the mistake is at least visible to a reader.

## Reference

- `docs/using-theorem.md` in the repo: the embedding API in full
- `docs/language-spec.md`: normative grammar and semantics
- `docs/tutorial.md`: empty database to multi-hop aggregate
- `docs/benchmarks.md`: what is measured, and what is only argued

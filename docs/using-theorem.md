# Using theorem in a project

Every self-contained snippet on this page is executed by
`tests/test_using_theorem.py`, so a snippet that stopped working fails CI
rather than misleading you. The ones that need a model or a file of your
own are marked, and their API names are checked instead.

## Install

theorem is not on PyPI yet, so install it from the repository:

```bash
uv add "theorem @ git+https://github.com/VishiATChoudhary/theorem.git@main"
# or
pip install "git+https://github.com/VishiATChoudhary/theorem.git@main"
```

Pin a commit rather than `main` if you want the language and the storage
format to hold still:

```bash
pip install "git+https://github.com/VishiATChoudhary/theorem.git@<sha>"
```

Optional extras add document ingest: `[pdf]` for PDFs, `[office]` for
docx/xlsx/pptx. The core package has **no dependencies at all**.

## Three APIs, and which one is yours

This is the only part of the library it is possible to get wrong, so it
is first.

| call | on failure | takes | use it when |
|---|---|---|---|
| `session.execute(program)` | **raises** | reads and writes | your code is the caller |
| `session.rows(program)` | **raises** | reads only | you want values, not rendered text |
| `session.run(program)` | **returns the error as text** | reads and writes | a *model* is the caller |

`run` returns errors as a string on purpose: it is the agent contract, and
a model that made a mistake needs the corrective message back verbatim so
it can retry. If your own code calls `run` and does not inspect the
string, a failed program looks exactly like a successful one. Call
`execute` instead and let the exception find you.

```python
from theorem import Schema, Session

with Session("./mydb", Schema()) as db:
    db.execute('derive class supplier from entity with {country: str}')
    db.execute('assert supplier {name: "VoltaChem", country: "DE"} as v')
    assert db.rows('find supplier where country = "DE" as s\nreturn s.name') == [
        ["VoltaChem"]
    ]
```

The language's error types are all importable from the top level, so one
`except` covers the lot:

```python
from theorem import ExecError, ParseError, Schema, Session, VerifyError

with Session("./mydb", Schema()) as db:
    db.execute('derive class supplier from entity with {country: str}')
    try:
        db.execute("find suppler as s\nreturn s.name")
    except (ParseError, VerifyError, ExecError) as e:
        assert 'unknown class "suppler". did you mean: supplier?' in str(e)
        assert "nothing was executed." in str(e)
```

A `VerifyError` is the good case: the whole program was checked before
anything ran, so the store is untouched. An `ExecError` from a program
that also writes can leave the writes before the failure committed, and
the message says how many.

## Pick a schema

- `Schema()` is the base: `entity`, plus the document classes the ingest
  pipeline uses. Derive your own domain classes from `entity`.
- `Schema.supply_chain()` adds the demo classes the [tutorial](tutorial.md)
  is written against. Useful for following along, not for your data.

Classes you derive are durable. They are rebuilt from lineage when the
session reopens, so declare them once rather than on every start:

```python
from theorem import Schema, Session

with Session("./mydb", Schema()) as db:
    if "supplier" not in db.schema.classes:
        db.execute("derive class supplier from entity with {country: str}")
        db.execute("derive class part from entity with {unit_cost: float}")
        db.execute("derive edge supplied_by(item: part, source: supplier)")
    db.execute('assert supplier {name: "VoltaChem", country: "DE"} as v')
    db.execute('assert part {name: "cell", unit_cost: 4.5} as c')
    db.execute("assert edge supplied_by(item: c, source: v)")
    assert db.rows(
        "find part as p\nfollow p supplied_by source as s\nreturn p.name, s.name"
    ) == [["cell", "VoltaChem"]]
```

Reopening that store finds `supplier` already declared.

## One writer at a time

A store directory is locked while a session holds it. Two processes
writing one path used to interleave their logs and hand out duplicate
ids; the second one now gets `StoreLocked` immediately.

```python
# not runnable here: the point is the second session failing
from theorem import Schema, Session, StoreLocked

try:
    db = Session("./mydb", Schema())
except StoreLocked:
    ...  # another process holds it
```

Readers are not blocked by this and see writes as they land. Use the
context manager, or call `close()`, so the lock is released promptly
rather than whenever the object is collected.

## Loading data you already have

For columns you already know, skip the model entirely:

```bash
theorem load parts.csv --db ./mydb --class part
theorem load links.csv --db ./mydb --edge supplied_by \
    --role item=part --role source=supplier
theorem stats --db ./mydb
```

Or in process, with a receipt of what landed:

```python
# not runnable here: needs a CSV of yours
from pathlib import Path

from theorem import load_nodes

receipt = load_nodes(db, Path("parts.csv"), "part")
print(receipt.written, "of", receipt.rows, "rows")
for note in receipt.skipped:
    print(note)
```

Both `load_nodes` and `load_edges` validate every row before writing any
of them, so a bad file is rejected whole rather than half-applied.

## Bounding a query

Reads run under a row ceiling and a wall-clock deadline. The defaults are
1,000,000 rows and 60 seconds; a read that would exceed either stops with
an error naming the limit rather than taking the process with it.

```python
# not runnable here: substitute a program of your own
from theorem import limits

with limits(seconds=5.0, max_rows=100_000):
    rows = db.rows(program_a_model_wrote)
```

Set these tighter than the default for anything a model authored.

## Letting a model write the queries

`answer` is the loop the [benchmarks](benchmarks.md) measure, shipped so
that you get the behaviour the numbers describe rather than a
reimplementation of it:

```python
# not runnable here: `ask` is your model
from theorem import answer

got = answer(db, "Which suppliers are in Germany?", ask=my_model)
print(got.rows)     # the answer
print(got.query)    # the program the model wrote
print(got.turns)    # how many attempts it took
print(got.errors)   # what it got wrong on the way
```

`ask` is any callable taking a prompt string and returning the model's
text. A query that fails is never partly applied, so a repair turn is a
fresh attempt rather than a cleanup.

To drive the loop yourself, `agent_prompt(schema, question, store)` builds
the prompt and `repair_prompt(query, error)` builds the retry. The schema
render only covers classes that hold data, so the prompt does not grow
with classes you declared and never filled.

## What is stable and what is not

theorem is 0.3. The language surface in the [spec](language-spec.md) is
what the benchmarks pin and is the least likely thing to move under you.
The storage format is versioned: a store written by a newer version
refuses to open on an older one and says so, rather than misreading it.

`theorem stats --db ./mydb` prints the counts, the log state, and memory
against the ceiling, which is the cheapest way to check a store still
holds what you think it does.

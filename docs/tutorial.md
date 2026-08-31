# Tutorial: productive in ten minutes

This walks a small supply-chain graph from empty database to multi-hop aggregate. Run everything in the REPL:

```bash
pip install "git+https://github.com/VishiATChoudhary/theorem.git@main"
theorem --repl --db ./tutorial-db
```

The REPL executes a block when you enter a blank line.

## 1. See the schema

```theorem
schema
```

The engine ships a demo supply-chain schema: classes (`product`, `part`, `supplier`) with typed properties, and edges declared as two named roles:

```text
uses(whole: product, component: part)
supplied_by(item: part, source: supplier) via{start_year, contract_end}
```

(the edges, abridged from the full render). `via{...}` lists the
properties an edge carries itself, which section 10 asks about.

Roles are how you traverse. There are no arrows anywhere in the language.

## 2. Write nodes with assert

```theorem
assert product {name: "PowerBank Pro", launch_year: 2025} as pb
assert part {name: "lithium cell", unit_cost: 4.2} as cell
assert supplier {name: "VoltaChem", country: "DE"} as volta
```

Every write returns a **receipt**: the created id, its position `@t-N`, the guards that ran, and any duplicate candidates found at write time. Bindings (`pb`, `cell`, `volta`) stay usable as write arguments for the rest of the session.

## 3. Connect them with edges

```theorem
assert edge uses(whole: pb, component: cell)
assert edge supplied_by(item: cell, source: volta)
```

Both roles are named explicitly. Passing a node of the wrong class to a role is a verify-time error; nothing executes.

## 4. Load a file instead of typing it

Writing a row at a time is fine for a handful. For a table you already
have, `load` writes it directly:

```bash
theorem load parts.csv --db mydb --class part
theorem load links.csv --db mydb --edge supplied_by \
    --role item=part --role source=supplier
```

CSV or JSONL. Columns must be properties the class declares and values
must match the declared types, or the load is refused and nothing is
written. Edge rows name their endpoints by `name` (or by id); a name that
matches two nodes is an error rather than a coin flip.

This path skips the dedup pass and the provisional-class quota, on the
grounds that a bulk load is an operator saying the file is the truth.
For a PDF or anything else whose structure is not already known, use
`theorem ingest`, which stages the document and has an agent extract from
it.

## 5. Read: find and follow

```theorem
find product where launch_year > 2024 as recent
follow recent uses component as parts
return parts.name
```

A query builds one binding table. `find` seeds rows; each `follow` extends every row through edges of the named type, arriving at the named role. `follow recent uses component` reads as: from `recent`, cross `uses` edges, arrive at the `component` role.

## 6. Make a mistake (on purpose)

```theorem-error
find product where lunch_year > 2024 as recent
return recent.name
```

```text
error: unknown property "lunch_year" on class product. did you mean: launch_year? in line 1
nothing was executed.
```

The whole program was verified before execution, so the error names the line, suggests the fix, and guarantees no partial effects. This is the core loop that makes agents reliable: mistakes are loud and cheap.

## 7. Aggregate in stages

```theorem
find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts desc budget 2000 tokens
```

`group by sups` groups by node identity (`group by sups.country` would group by value; the difference is visible in the spelling). The aggregate names its input group and its output column. Adding a column to `return` can never change the grouping, because grouping happened two lines earlier.

## 8. Reach: how far does this go

A single `follow` crosses one edge. Questions about dependency graphs are
about reach: what does this contain, all the way down.

```theorem
derive edge contains(whole: part, component: part)
assert part {name: "Anode", unit_cost: 0.4} as anode
assert edge contains(whole: cell, component: anode)
```

```theorem
find part where name = "Battery cell" as cell
follow cell contains component upto any as inner
return inner.name
```

`upto N` walks the edge 1 to N times; `upto any` walks it until nothing
new is reached. Every arrival at any depth is part of the answer.

A `where` on a transitive follow filters what comes back, not where the
walk may pass, so cheap parts inside an expensive assembly are still
found:

```theorem
find part where name = "Battery cell" as cell
follow cell contains component upto any where unit_cost < 1.0 as cheap
return cheap.name
```

Cycles terminate. Reach is a set of nodes rather than of paths, so a part
two routes lead to is one answer.

## 9. Rows that would otherwise disappear

A `follow` drops rows that match nothing. That is wrong for "how many
parts does each product use", because a product using none should report
zero, not vanish:

```theorem
find product as p
follow p uses component as parts or none
group by p as g
count distinct g.parts as n
return p.name, n
```

`or none` keeps the row with nothing bound to `parts`.

A line holding only `or` starts an alternative branch. The branches are
unioned, and everything after the last one applies to the union:

```theorem
find product where name = "PowerBank X" as p
follow p uses component as parts
or
find product where name = "PowerBank Y" as p
follow p uses component as parts
count distinct parts as n
return n
```

Reusing a name means the same node, which is how you say "both, and the
same one":

```theorem
find part as parts
follow parts supplied_by source where country = "DE" as german
follow parts supplied_by source where country = "JP" as japanese
return parts.name
```

Only parts with a German supplier *and* a Japanese one survive, because
both follows extend the same row.

## 10. Ask about the relationship, and filter after counting

`via.<prop>` inside a follow's `where` reads a property of the edge
rather than of the node you arrive at. `none` is the absent value:

```theorem
find part as parts
follow parts supplied_by source as sups where via.contract_end = none
return parts.name, sups.name
```

`keep` filters the rows that exist at that point. After an aggregate the
rows are groups, so counting first and keeping second is how "the
suppliers with more than three parts" is asked:

```theorem
find part as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n
keep g where n > 3
return sups.name, n order by n desc
```

`return distinct` collapses repeated values, where plain `return`
collapses repeated nodes. Two suppliers sharing a name are two rows under
`return` and one under `return distinct`.

## 11. Use it from Python

The CLI is a wrapper. An application embeds the session directly:

```python
from theorem import Schema, Session

with Session("mydb", Schema()) as db:
    print(db.run("derive class supplier from entity with {country: str}"))
    print(db.run('assert supplier {name: "VoltaChem", country: "DE"} as v'))
    print(db.run('find supplier where country = "DE" as s\nreturn s.name'))
```

`Schema()` is the base schema: `entity` to derive your own classes from,
plus the document classes the ingest pipeline uses.
`Schema.supply_chain()` adds the demo classes this tutorial uses, and is
what the CLI opens with unless you pass `--schema base`.

The session holds an exclusive lock on the directory for as long as it is
open, so close it (or use it as a context manager, as above) before
another process opens the same database.

## 12. Let an agent write the queries

The prompt the benchmarks use is the prompt the package ships:

```python
from theorem import Schema, Session, answer

with Session("mydb", Schema.supply_chain()) as db:
    got = answer(db, "Which suppliers ship more than three parts?", your_model)
    print(got.rows, got.turns, got.errors)
```

`your_model` is any callable taking a prompt and returning text; the
benchmarks pass Haiku. `answer` is the loop those benchmarks measure:
write, run, and on an error hand the error back verbatim and try again,
three turns by default. A failed query is never partly applied, so a
repair is a fresh attempt rather than a cleanup.

The two halves are exported separately if you want your own loop:

```python
from theorem import agent_prompt, repair_prompt

prompt = agent_prompt(db.schema, question, db.store)
```

Passing the store renders only the classes that hold data, which is both
cheaper and less of an invitation to traverse somewhere nothing lives.

The tutorial inside that prompt is versioned by its own hash
(`theorem.prompt.fingerprint()`). The benchmarks key their frozen query
files by it, so a published number can never come from a prompt other
than the one it names.

## 13. Budgets and continuations

`budget 2000 tokens` caps the serialized result. On overflow the result truncates at a row boundary and prints a handle:

```text
truncated: 40 more. resume with: continue @c1a
```

```text
continue @c1a budget 500 tokens
```

## 14. Know where you stand

```bash
theorem stats --db mydb
```

```text
store: mydb
  nodes:            4,327
  edges:           18,991
  wal:              4,178 records
  snapshots:            1 (newest run-23318.json)
  in memory:      27.6 MB (estimated at 6.7 KB/node)
  a 32 GB machine holds about 3,384,690 nodes with room to query them;
  this store is at 0.1% of that.
```

Everything is in memory with no spill to disk, so the ceiling is real and
worth watching. `stats` does not take the lock, because a store being
written by someone else is exactly when its numbers are worth reading.

## 15. The maintenance surface

When a duplicate slips in, the receipt tells you at write time:

```theorem
assert supplier {name: "Volta Chem", country: "DE"} as v2
```

The receipt lists `volta` as a dup candidate. You resolve it explicitly, either way:

```theorem
merge v2, volta
```

Or, if they are genuinely two companies, say so once and the pair never
comes back:

```text
distinct v2, volta reason "different legal entities"
```

`merge` keeps the older node as survivor, aliases the absorbed id forever, and records both pre-merge states in lineage. Also available: `retire` (temporal invalidation with history), `flag` (mark a node as having caused a failure), `refine` (split a blob into typed children with lineage), `compact` (summarize a node set), `derive class` (provisional subclass, whose instances a `find` on the base class also reads), and per-node health you can query like any property:

```theorem
find nodes where health.loss > 0.8 as sick
return sick.id, sick.health
```

## Next

The [language spec](language-spec.md) has the complete grammar and precise semantics for everything you just used.

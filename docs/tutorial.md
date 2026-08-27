# Tutorial: productive in ten minutes

This walks a small supply-chain graph from empty database to multi-hop aggregate. Run everything in the REPL:

```bash
pip install theorem
theorem --repl --db ./tutorial-db
```

The REPL executes a block when you enter a blank line.

## 1. See the schema

```
schema
```

The engine ships a demo supply-chain schema: classes (`product`, `part`, `supplier`) with typed properties, and edges declared as two named roles:

```
uses(whole: product, component: part)
supplied_by(item: part, source: supplier)
```

Roles are how you traverse. There are no arrows anywhere in the language.

## 2. Write nodes with assert

```
assert product {name: "PowerBank Pro", launch_year: 2025} as pb
assert part {name: "lithium cell", unit_cost: 4.2} as cell
assert supplier {name: "VoltaChem", country: "DE"} as volta
```

Every write returns a **receipt**: the created id, its position `@t-N`, the guards that ran, and any duplicate candidates found at write time. Bindings (`pb`, `cell`, `volta`) stay usable as write arguments for the rest of the session.

## 3. Connect them with edges

```
assert edge uses(whole: pb, component: cell)
assert edge supplied_by(item: cell, source: volta)
```

Both roles are named explicitly. Passing a node of the wrong class to a role is a verify-time error; nothing executes.

## 4. Read: find and follow

```
find product where launch_year > 2024 as recent
follow recent uses component as parts
return parts.name
```

A query builds one binding table. `find` seeds rows; each `follow` extends every row through edges of the named type, arriving at the named role. `follow recent uses component` reads as: from `recent`, cross `uses` edges, arrive at the `component` role.

## 5. Make a mistake (on purpose)

```
find product where lunch_year > 2024 as recent
return recent.name
```

```
error: unknown property "lunch_year" on class product. did you mean: launch_year? in line 1
nothing was executed.
```

The whole program was verified before execution, so the error names the line, suggests the fix, and guarantees no partial effects. This is the core loop that makes agents reliable: mistakes are loud and cheap.

## 6. Aggregate in stages

```
find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts desc budget 2000 tokens
```

`group by sups` groups by node identity (`group by sups.country` would group by value; the difference is visible in the spelling). The aggregate names its input group and its output column. Adding a column to `return` can never change the grouping, because grouping happened two lines earlier.

## 7. Budgets and continuations

`budget 2000 tokens` caps the serialized result. On overflow the result truncates at a row boundary and prints a handle:

```
truncated: 40 more. resume with: continue @c1a
```

```
continue @c1a budget 500 tokens
```

## 8. The maintenance surface

When a duplicate slips in, the receipt tells you at write time:

```
assert supplier {name: "Volta Chem", country: "DE"} as v2
```

The receipt lists `volta` as a dup candidate. You resolve it explicitly, either way:

```
merge v2, volta
distinct v2, volta reason "different legal entities"
```

`merge` keeps the older node as survivor, aliases the absorbed id forever, and records both pre-merge states in lineage. Also available: `retire` (temporal invalidation with history), `flag` (mark a node as having caused a failure), `refine` (split a blob into typed children with lineage), `compact` (summarize a node set), `derive class` (provisional subclass), and per-node health you can query like any property:

```
find nodes where health.loss > 0.8 as sick
return sick.id, sick.health
```

## Next

The [language spec](language-spec.md) has the complete grammar and precise semantics for everything you just used.

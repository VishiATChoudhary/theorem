# Language spec

The normative grammar and semantics for theorem v0. Canonical forms: exactly one spelling per operation, no optional shorthands beyond what is written here.

## Program structure

A program is a sequence of statements, one per logical line. A physical line starting with whitespace continues the previous logical line. Comments: a line whose first non-blank character sequence is `# ` (hash space), or an unindented line starting with `#` that is not inside a continuation. Node ids like `#p-71002` on continuation lines are never comments.

## Grammar (EBNF)

```
program     := statement*
statement   := read_stmt | write_stmt | util_stmt

read_stmt   := find | follow | group | aggregate | compute | return | continue
find        := "find" target ["where" cond] ["order" "by" col ["desc"]] "as" NAME
target      := CLASSNAME | "nodes" | "dup_candidates" | "class"
follow      := "follow" NAME EDGENAME ROLENAME ["where" cond] "as" NAME
               ; cond filters the arrival node's properties
group       := "group" "by" col "as" NAME
aggregate   := AGGVERB ["distinct"] col "as" NAME     ; AGGVERB: count|sum|avg|min|max
compute     := "compute" col COMPOP col "as" NAME     ; COMPOP: plus|minus|times|over|same
return      := "return" col ("," col)* ["order" "by" col ["desc"]]
               ["limit" INT] ["budget" INT "tokens"] ["after" POSITION]
continue    := "continue" HANDLE ["budget" INT "tokens"]

write_stmt  := assert_node | assert_edge | merge | distinct_s | refine
             | compact | retire | flag | derive
assert_node := "assert" CLASSNAME props ["source" PROVENANCE] "as" NAME
assert_edge := "assert" "edge" EDGENAME "(" ROLENAME ":" ref ","
               ROLENAME ":" ref ")" ["source" PROVENANCE]
merge       := "merge" ref "," ref ["prefer" ("newest" | "source" PROVENANCE)]
distinct_s  := "distinct" ref "," ref "reason" STRING
refine      := "refine" ref "into" CLASSNAME "with" mapping "as" NAME
compact     := "compact" NAME "as" NAME props
retire      := "retire" ref "reason" STRING
flag        := "flag" ref "reason" STRING
derive      := "derive" "class" NAME "from" CLASSNAME "with" propdecls

util_stmt   := "schema"

cond        := clause ("and" clause | "or" clause)*   ; "and" binds tighter
clause      := col OP literal                          ; OP: = != > >= < <= contains
col         := NAME ["." NAME ["." NAME]]              ; e.g. sups.name, health.loss
props       := "{" NAME ":" literal ("," NAME ":" literal)* "}"
mapping     := "{" NAME ":" "col" STRING ("," NAME ":" "col" STRING)* "}"
propdecls   := "{" NAME ":" TYPENAME ("," NAME ":" TYPENAME)* "}"  ; TYPENAME: str|int|float|bool
literal     := STRING | NUMBER | "true" | "false" | ATTACH
ref         := NAME | NODEID
NODEID      := "#" [a-z]+ "-" [a-z0-9]+
POSITION    := "@t-" [0-9]+
HANDLE      := "@c" [a-z0-9]+
PROVENANCE  := ("doc:" | "attach:") [^ ]+
ATTACH      := "attach:" [^ ]+
STRING      := '"' ... '"'
```

## Read semantics

**Binding table.** A query builds one binding table (SPARQL solution-mapping style). Each `as NAME` is a column. `find` seeds rows. `follow X edge role as Y` extends every row: for each row, for each edge of type `edge` incident to the node in column X, bind the node at `role` to Y. Rows multiply; rows with no match are dropped. Homomorphism semantics: repeated nodes are allowed. Edge instances are per-row unique (trail semantics, matching Cypher's MATCH default).

**Roles.** An edge type declares exactly two roles: `uses(whole: product, component: part)`. `follow parts supplied_by source` means: arrive at the `source` role. Asking to arrive at the role your binding already occupies is a verifier type error when endpoint classes differ.

**group / aggregate.** `group by sups` groups by node identity; `group by sups.country` groups by value. The difference is visible in the spelling. Aggregates consume a group name: `count distinct g.parts as n_parts` counts distinct node bindings of column `parts` within each group of `g`. An aggregate over a plain (non-group) binding is a global aggregate: it collapses the table to one row. `distinct` dedups bindings before property extraction; aggregates over a property skip members where the property is null.

**String matching.** `=`, `!=`, and `contains` on strings are case-insensitive and accent-insensitive (casefold, then NFKD accent strip). Agents transliterate names ("Jose Calderon" for "José Calderón"), and silently matching nothing is the worse failure mode. Numeric comparison is exact. Known tradeoff: two distinct nodes whose names differ only by case or accent both match an exact-looking equality; the dedup pipeline flags such pairs and the agent resolves them with `merge`/`distinct`.

**compute.** `compute p1.height_cm minus p2.height_cm as diff` evaluates per row; `same` yields a boolean. Word operators, no symbols, one operation per line. `compute ... same` errors when either operand is unset rather than reporting two missing values as equal.

**return.** Serializes the requested columns. `order by` sorts (nulls last in both directions), `limit` bounds rows, `budget` bounds tokens (default 2000 when unstated). On overflow: truncate at a row boundary and emit `truncated: K more. resume with: continue @cXXXX`. Token counting in v0 is `len(text) // 4`, a documented heuristic.

**Result format.** Header line `results: <shown> of <total>[, complete|budget hit]`. Each detailed node prints once as `class "name" {props}` with its result-relevant edges indented under it; referenced nodes are named only. Ordering: distance from query anchors, then recency. Tabular returns (aggregates, property lists) print rows as `value, value, ...` under a `columns:` header.

**Verify before execute.** The whole program is verified against the live schema before anything runs. Unknown class, edge, role, or property produces a corrective error naming the line, offering the nearest schema alternatives, and stating `nothing was executed.` Partial execution never happens.

## Write semantics

Every write returns a **receipt**: created and changed ids, position `@t-N`, the guards that ran, and dup candidates (the synchronous blocking stage inline; the async similarity stage lands in the ledger).

- **merge a, b**: survivor is the older node; the absorbed id becomes a permanent alias; lineage records both pre-merge states. Conflicting properties resolve per the policy, default `prefer newest`.
- **distinct a, b reason "..."**: durable pair suppression; the pair never resurfaces as a dup candidate.
- **refine blob into class with {prop: col "colname"} as name**: the blob payload must be tabular (`attach:` CSV payloads parse at assert time). Creates one child per row, each with `origin` lineage to the blob; the blob moves to state `composite` and is retained cold.
- **compact binding as name {props}**: replaces the bound node set with one summary node (state `composite`, parent lineage).
- **retire ref reason "..."**: temporal invalidation. The node keeps its history and is excluded from current-time reads.
- **flag ref reason "..."**: marks the node as having caused a downstream failure; feeds `health.query`.
- **derive class name from base with {...}**: creates a provisional subclass with an instance quota (500 in v0). Status is queryable via `find class`.

## Dedup

Blocking key: `(class, first 4 chars of casefolded-alnum name)`. The sync stage on every assert checks the block; similarity is `difflib.SequenceMatcher.ratio()` with a name-containment boost (one normalized name being a strict prefix of the other lifts the score to at least 0.9). Candidates need a score of at least 0.85. The async stage (`dedup.sweep()`) sweeps cross-block near-names per class. Candidates are queryable: `find dup_candidates where class = supplier order by score as dups`.

## Health

Four subscores in `[0,1]`, computed incrementally, queryable as `health.loss`, `health.query`, `health.structure`, `health.staleness`:

- **loss** = min(1, conflicting re-asserts of the same property / 5)
- **query** = min(1, flags / 3)
- **structure** = max(supernode: min(1, degree/100); blob traversal: min(1, traversals into blob payload / 50); orphan: 0.3 if degree is 0)
- **staleness** = min(1, positions since last confirming write / 1000)

## Storage

Single process, disaggregated shape preserved: an append-only WAL (`wal.jsonl`, one JSON record per write, position = line number); in-memory state rebuilt on open by replay; `snapshot()` writes an immutable run file `runs/run-<pos>.json` and truncates the WAL. A torn final WAL line (crash mid-append) is recovered by replaying the longest valid prefix. Single logical writer. Lineage records live in the WAL and are never pruned.

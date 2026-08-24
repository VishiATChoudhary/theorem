# GraphLang v0 Design Spec

Working name: **GraphLang** (final name TBD; nothing depends on it). File extension `.gl`, Python package `graphlang`.

This spec freezes the open decisions from `research/design-briefing/trellis-design-briefing.tex` (all 18 decisions resolved to their recommended options) and resolves the syntax conflicts between the briefing and `research/design-briefing/query-language-explainer.tex` (explainer wins every conflict; it is newer).

## Decisions locked

| # | Decision | Choice |
|---|----------|--------|
| 1 | Verb surface | B: two-tier (core read verbs + maintenance verbs, taught separately) |
| 2 | Edge direction | A: role-named only, no direction glyphs |
| 3 | Cold start | A grammar prompting (baseline) + B schema-closed validation (parse-time in v0; constrained decoding later) |
| 4 | Pattern semantics | A-shaped: one fixed semantics, nothing exposed. v0 uses per-row edge-uniqueness (trail semantics, Cypher's MATCH default) so results agree with CypherBench gold answers; nodes may repeat, edge instances may not |
| 5 | Granularity states | A: `blob`, `composite`, `atom` |
| 6 | Refinement mapping | A: agent supplies mapping inline |
| 7 | Lineage | A: full lineage forever (v0: lineage log on disk, never pruned) |
| 8 | Merge reconciliation | A: per-merge policy, default `prefer newest` |
| 9 | Dedup latency | A: sync blocking-stage on every assert, similarity stage async |
| 10 | Distinct assertions | A: pair-level suppression only |
| 11 | Health shape | A: four named subscores, no combined number |
| 12 | Failure attribution | A: explicit `flag` verb only |
| 13 | Budget overflow | A: truncate + continuation token |
| 14 | Relevance ordering | A: query-structural (anchor distance, then recency) |
| 15 | Storage substrate | A-shaped: v0 = same architecture in one process; WAL + immutable snapshot runs on local disk (SlateDB swap-in later) |
| 16 | Consistency | A: single-writer positions in receipts; `after @t-N` read barrier is a no-op in v0 (single process) but parsed and honored |
| 17 | Partitioning | A: none in v0 (single shard); node-id hash reserved |
| 18 | Vector index | A-shaped: v0 similarity stage = in-process string-similarity ANN stand-in, same async pipeline shape |

## Syntax conflict resolutions

- Grouping: `group by <col> as <name>` (explainer). The briefing's `group X by Y` form is dead.
- `limit N` exists on `return` (row bound), alongside `budget N tokens` (token bound). The explainer's "no limit" prose refers only to Q2 not needing one.
- `count distinct` is `count` with optional `distinct` modifier.

## Grammar (EBNF)

A program is a sequence of statements. One statement per logical line. A physical line starting with whitespace continues the previous logical line. Comments: a line whose first non-blank character sequence is `# ` (hash space), or an unindented line starting with `#` that is not inside a continuation; node ids like `#p-71002` on continuation lines are never comments.

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
               ; scalar arithmetic / equality on two bound values; "same"
               ; yields true/false. one row expected per operand column
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

Canonical forms: exactly one spelling per operation. No optional shorthands beyond what's written above.

## Semantics

**Binding table.** A query builds one binding table (SPARQL solution-mapping style). Each `as NAME` is a column. `find` seeds rows. `follow X edge role as Y` extends every row: for each row, for each edge of type `edge` incident to the node in column X, bind the node at `role` to Y (rows multiply; rows with no match are dropped). Homomorphism semantics: repeated nodes allowed.

**Roles.** Edge type declares exactly two roles: `uses(whole: product, component: part)`. `follow parts supplied_by source` means: arrive at the `source` role. Asking to arrive at the role your binding already occupies is a verifier type error when endpoint classes differ.

**group/aggregate.** `group by sups` groups by node identity; `group by sups.country` groups by value (visibly different spelling). Aggregates consume a group name: `count distinct g.parts as n_parts` counts distinct node bindings of column `parts` within each group of `g`. An aggregate over a plain (non-group) binding is a global aggregate: `count distinct v as n` collapses the table to one row. `distinct` dedups bindings before property extraction; aggregates over a property skip members where the property is null.

**String matching.** `=`, `!=`, and `contains` on strings are case-insensitive and accent-insensitive (casefold + NFKD strip): agents transliterate names ("Jose Calderon" for "José Calderón"), and silently matching nothing is the worse failure. Numeric comparison unchanged.

**compute.** `compute p1.height_cm minus p2.height_cm as diff` evaluates per row; `same` yields a boolean. Word operators, no symbols, one op per line.

**return.** Serializes the requested columns. `order by` sorts, `limit` bounds rows, `budget` bounds tokens (default 2000 when unstated). Overflow: truncate at row boundary, emit `truncated: K more. resume with: continue @cXXXX`. Token counting v0: `len(text) // 4` (documented heuristic).

**Result format.** Incident encoding: header line `results: <shown> of <total>[, complete|budget hit]`; each detailed node printed once as `class "name" {props}` with its result-relevant edges indented under it (`edge_type -> class "name"` / `edge_type <- class "name"`); referenced nodes named only. Ordering: distance from query anchors, then recency. For tabular returns (aggregates / property lists), rows print as `value, value, ...` under a `columns:` header with declared count.

**Verify before execute.** Whole program is verified against the live schema before anything runs: unknown class/edge/role/property → corrective error naming the line, offering nearest schema alternatives (difflib), stating `nothing was executed.` Partial execution never happens.

**Writes.** Every write returns a receipt: created/changed ids, position `@t-N`, guards run, dup candidates (sync blocking stage inline; async similarity stage lands in the ledger). `merge a, b`: survivor = older node; absorbed id becomes permanent alias; lineage records both pre-merge states; policy default `prefer newest` per conflicting property. `distinct a, b reason "..."`: durable pair suppression. `refine blob into class with {prop: col "colname"}`: blob payload must be tabular (attach:csv payloads parsed at assert time); creates one child per row, each with `origin` lineage to blob; blob → state `composite`, retained cold. `compact <binding> as <name> {props}`: replaces the bound node set with one summary node (state `composite` parent lineage); values may use `avg(col.prop)`-free literal props only in v0. `retire`: temporal invalidation; node keeps history, excluded from current-time reads. `derive class`: new subclass, provisional status, quota 500 instances, promotion out of scope for v0 (status queryable).

**Dedup.** Blocking key: `(class, first 4 chars of casefolded-alnum name)` (4, not 6, so short names like "Ionix" block with their extensions). Sync stage on every assert checks the block, similarity via `difflib.SequenceMatcher.ratio()` with a name-containment boost (one normalized name a strict prefix of the other lifts the score to at least 0.9, so "Ionix Co" vs "Ionix" is a candidate); candidates need score `>= 0.85`. Async stage (explicit `dedup.sweep()`) sweeps cross-block near-names per class. Candidates queryable: `find dup_candidates where class = supplier order by score as dups`.

**Health.** Four subscores in `[0,1]`, computed incrementally, queryable as `health.loss`, `health.query`, `health.structure`, `health.staleness`. v0 definitions: loss = min(1, conflicting re-asserts of same property / 5); query = min(1, flags / 3); structure = max(supernode: min(1, degree/100), blob-traversal: min(1, traversals into blob payload / 50), orphan: 0.3 if degree==0); staleness = min(1, positions since last confirming write / 1000).

**Storage (engine v0).** Single process, disaggregated shape preserved: append-only WAL (`wal.jsonl`, one JSON record per write, position = line number); in-memory state rebuilt on open by replay; `snapshot()` writes immutable run file `runs/run-<pos>.json` and truncates WAL; nodes stored with incident edge lists (serialization ≈ copy). Single logical writer. Lineage records in WAL, never pruned.

## Evaluation

Harness: CypherBench (megagonlabs/cypherbench) slice, one domain graph, ≥40 questions stratified by hop count. Two conditions, same model (`claude -p`, haiku for cost): (A) text2cypher baseline executed on Neo4j if docker available, else compared against published frontier numbers (Claude 3.5 Sonnet 61.6% EX, GPT-4o 60.2%); (B) GraphLang via grammar prompt (compact EBNF + 6 worked examples), executed on our engine over the same graph loaded from CypherBench JSON. Metric: execution accuracy vs gold answers (set comparison, order-insensitive except explicit order-by questions). Slices reported: overall, multi-hop (>=2 hops), 1-hop.

**Success claim target:** GraphLang condition beats the text2cypher condition on the multi-hop slice (the Anka-predicted win zone); overall parity or better.

## Final deliverable

Spider (radar) diagram comparing GraphLang vs text2cypher baseline across ≥5 axes (overall EX accuracy, multi-hop EX, 1-hop EX, syntax validity rate, result token economy inverted-normalized), saved as `eval/out/spider.png`, built per dataviz skill.

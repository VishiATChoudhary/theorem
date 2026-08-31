# Language spec

The normative grammar and semantics for theorem v0.

**Canonical forms.** Exactly one spelling per operation, and no optional shorthands beyond what is written here. The point is that two correct answers to the same question are the same program, which makes plan caching and auditing possible.

There is one redundant variant, and the parser removes it rather than carrying it: a condition may name the binding its own statement creates (`where l.area_km2 < 1` for `where area_km2 < 1`), and the two parse to the same tree. Models write the qualified form constantly and rejecting it cost four points of accuracy, so the language accepts it and normalizes it away. Canonicality therefore holds of the parsed program, not of the input text. `theorem.canonical(program)` renders a program back to its canonical text, so a cache can key on a string again: two programs are the same query exactly when their canonical text is equal. It also drops what the grammar defaults (`budget 2000 tokens`, `upto 1`) and settles spellings that mean the same number (`3.0` and `3`).

## Program structure

A program is a sequence of statements, one per logical line. A physical line starting with whitespace continues the previous logical line. Comments: a line whose first non-blank character sequence is `# ` (hash space), or an unindented line starting with `#` that is not inside a continuation. Node ids like `#p-71002` on continuation lines are never comments.

## Grammar (EBNF)

```
program     := statement*
statement   := read_stmt | write_stmt | util_stmt

read_stmt   := find | follow | group | aggregate | keep | compute
             | return | continue | or
find        := "find" target ["where" cond] ["order" "by" col ["desc"]] "as" NAME
target      := CLASSNAME | "nodes" | "dup_candidates" | "class"
follow      := "follow" NAME EDGENAME ROLENAME ["where" cond]
               ["upto" (INT | "any")] "as" NAME ["or" "none"]
               ; cond filters the arrival node's properties and the edge's
group       := "group" "by" col "as" NAME
aggregate   := AGGVERB ["distinct"] col "as" NAME     ; AGGVERB: count|sum|avg|min|max
keep        := "keep" NAME "where" cond
compute     := "compute" col COMPOP col "as" NAME     ; COMPOP: plus|minus|times|over|same
return      := "return" ["distinct"] col ("," col)* ["order" "by" col ["desc"]]
               ["limit" INT] ["budget" INT "tokens"] ["after" POSITION]
continue    := "continue" HANDLE ["budget" INT "tokens"]
or          := "or"                                   ; alone on its line

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
                 ["quota" INT] ["dedup" NUMBER]
             | "derive" "edge" EDGENAME "(" ROLENAME ":" CLASSNAME ","
                 ROLENAME ":" CLASSNAME ")"

util_stmt   := "schema"

cond        := clause ("and" clause | "or" clause)*   ; "and" binds tighter
clause      := col OP literal                          ; OP: = != > >= < <= contains
col         := NAME ["." NAME ["." NAME]]              ; e.g. sups.name, health.loss
             | "via" "." NAME                          ; a follow's edge property
             ; in a find's or follow's own condition, a leading NAME that
             ; is the statement's own "as" name is optional and ignored
props       := "{" NAME ":" literal ("," NAME ":" literal)* "}"
mapping     := "{" NAME ":" "col" STRING ("," NAME ":" "col" STRING)* "}"
propdecls   := "{" NAME ":" TYPENAME ("," NAME ":" TYPENAME)* "}"  ; TYPENAME: str|int|float|bool
literal     := STRING | NUMBER | "true" | "false" | "none" | ATTACH
                                                       ; none = absent
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

**A condition may name its own binding.** `follow c contains part as l where l.unit_cost < 1` means the same as `where unit_cost < 1`: a follow's condition is about the node being arrived at, and `l` is the name for that node. The same holds for `find x as p where p.prop = v`. The same holds for a `find`'s `order by`. Only the statement's own name is stripped; any other binding keeps meaning what it meant, so `where r.prop` in a follow that binds `l` is still a reference to `r` and is checked as one.

**Alternative branches (`or`).** A line holding only the word `or` ends the current branch and starts another. Each branch is a `find`/`follow` sequence evaluated independently; the branches' rows are unioned before whatever follows. Rows are a set, so a node found by two branches answers once. Everything after the last branch (group, aggregate, keep, compute, return) applies to the union, which is how "how many players played for either team" is one query rather than two.

**Optional traversal (`or none`).** `follow t playsFor player as p or none` keeps a row whose node has no matching edge, binding nothing to `p`. Without it the row disappears and a per-thing count cannot come out zero: a team with no players simply vanishes from the answer instead of reporting 0. An optional follow is a question asked about a row rather than a continuation of its path, so the edge that reached the row is available to it again; the trail rule does not apply across it.

**Edge properties (`via.<prop>`).** Inside a follow's `where`, `via.<prop>` reads a property of the edge being walked rather than of the node being arrived at. `follow p playsFor team as t where via.start_year <= 1983` asks about the tenure, not the team. `none` is the absent value: `via.end_year = none` is a relationship that has not ended, distinct from one that ended at a value you did not match. `via.` is meaningful only within a `follow`; the verifier rejects it elsewhere.

**Transitive traversal (`upto`).** `upto N` walks the edge 1 to N times; `upto any` walks it until a round reaches nothing new. Every arrival at any depth is part of the answer, so "everything this assembly contains, all the way down" is one statement. A `where` on a transitive follow filters what is *returned*, not where the walk may pass: cheap parts inside an expensive engine are still found. Reach is a set of nodes, not of paths, so a node two routes lead to is one answer and the route recorded for it is a shortest one. A cycle terminates. A reused name constrains a transitive follow exactly as it constrains a one-hop one: the arrival must be that same node, and the walk continues past an arrival that is not, because a longer route may still land on it.

**keep.** `keep g where n > 3` filters the rows that exist at that point in the pipeline. After an aggregate the rows are groups, so this is how "the awards with more than twenty recipients" is asked: count first, then keep. Before an aggregate it filters plain rows. There is one rule rather than a having-clause that only works in one position.

**Name reuse is a join.** Binding a name that is already bound constrains the two to be the same node rather than shadowing the first. `follow p receivesAward award where name = "MVP" as mvp` followed by a second follow arriving at `p` keeps only rows where both hold of the same player. This is how "both, and the same one" is said.

**return distinct.** Plain `return` collapses repeated *nodes*; `return distinct` collapses repeated *values*. Two people who share a name are two rows under `return` and one under `return distinct`. Use `count distinct` for the same reason when a node is reachable by several paths.

**group / aggregate.** `group by sups` groups by node identity; `group by sups.country` groups by value. The difference is visible in the spelling. Aggregates consume a group name: `count distinct g.parts as n_parts` counts distinct node bindings of column `parts` within each group of `g`. An aggregate over a plain (non-group) binding is a global aggregate: it collapses the table to one row. `distinct` dedups bindings before property extraction; aggregates over a property skip members where the property is null.

**String matching.** `=`, `!=`, and `contains` on strings are case-insensitive and accent-insensitive (casefold, then NFKD accent strip). Agents transliterate names ("Jose Calderon" for "José Calderón"), and silently matching nothing is the worse failure mode. Numeric comparison is exact. Known tradeoff: two distinct nodes whose names differ only by case or accent both match an exact-looking equality; the dedup pipeline flags such pairs and the agent resolves them with `merge`/`distinct`.

**compute.** `compute p1.height_cm minus p2.height_cm as diff` evaluates per row; `same` yields a boolean. Word operators, no symbols, one operation per line. `compute ... same` errors when either operand is unset rather than reporting two missing values as equal.

**return.** Serializes the requested columns. `order by` sorts (nulls last in both directions), `limit` bounds rows, `budget` bounds tokens (default 2000 when unstated). On overflow: truncate at a row boundary and emit `truncated: K more. resume with: continue @cXXXX`. Token counting in v0 is `len(text) // 4`, a documented heuristic.

**Result format.** Header line `results: <shown> of <total>[, complete|budget hit]`. Each detailed node prints once as `class "name" {props}` with its result-relevant edges indented under it; referenced nodes are named only. Ordering: distance from query anchors, then recency. Tabular returns (aggregates, property lists) print rows as `value, value, ...` under a `columns:` header.

**Verify before execute.** The whole program is verified against the live schema before anything runs. Unknown class, edge, role, or property produces a corrective error naming the line, offering the nearest schema alternatives, and stating `nothing was executed.` A program that fails to verify never partly runs.

A program that verifies can still fail while running, on something the schema cannot predict: a quota reached, a merge of two nodes that are already one. Execution is not a transaction. Each write commits as it happens and returns its own receipt, and a failure stops the program with the writes before it committed. The error says how many those were, because the next thing an agent does depends on it.

## Write semantics

Every write returns a **receipt**: created and changed ids, position `@t-N`, the guards that ran, and dup candidates (the synchronous blocking stage inline; the async similarity stage lands in the ledger).

- **merge a, b**: survivor is the older node; the absorbed id becomes a permanent alias; lineage records both pre-merge states. Conflicting properties resolve per the policy, default `prefer newest`.
- **distinct a, b reason "..."**: durable pair suppression; the pair never resurfaces as a dup candidate.
- **refine blob into class with {prop: col "colname"} as name**: the blob payload must be tabular (`attach:` CSV payloads parse at assert time). Creates one child per row, each with `origin` lineage to the blob; the blob moves to state `composite` and is retained cold.
- **compact binding as name {props}**: replaces the bound node set with one summary node (state `composite`, parent lineage).
- **retire ref reason "..."**: temporal invalidation. The node keeps its history and is excluded from current-time reads.
- **flag ref reason "..."**: marks the node as having caused a downstream failure; feeds `health.query`.
- **derive class name from base with {...}**: creates a provisional subclass with an instance quota (500 in v0, `quota N` to change it; `dedup R` sets the class's dup threshold). Status is queryable via `find class`.
- **derive edge name(role: class, role: class)**: declares an edge type at runtime, with exactly two roles. Both survive a restart: the derivation is a lineage record, and a session rebuilds the schema entries a previous process created.

## Dedup

Blocking key: `(class, first 4 chars of casefolded-alnum name)`. The sync stage on every assert checks the block; similarity is `difflib.SequenceMatcher.ratio()` with a name-containment boost (one normalized name being a strict prefix of the other lifts the score to at least 0.9). Candidates need a score of at least 0.85. The async stage (`dedup.sweep()`) sweeps cross-block near-names per class. Candidates are queryable: `find dup_candidates where class = supplier order by score as dups`.

## Health

Four subscores in `[0,1]`, computed incrementally, queryable as `health.loss`, `health.query`, `health.structure`, `health.staleness`:

- **loss** = min(1, conflicting re-asserts of the same property / 5)
- **query** = min(1, flags / 3)
- **structure** = max(supernode: min(1, degree/100); blob traversal: min(1, traversals into blob payload / 50); orphan: 0.3 if degree is 0)
- **staleness** = min(1, positions since last confirming write / 1000)

## Compatibility

theorem is pre-1.0 and versioned by semver, which before 1.0 means the minor
number carries breaking changes: 0.1 to 0.2 refused a second writer where it
had silently lost one of them, and that is the kind of change a minor bump is
for. Patch releases do not change behaviour a caller can see.

What a version promises:

- **The log format.** A store written by any 0.x release opens in any later
  0.x release. Records are self-describing objects with an `op`; an unknown one
  is a loud error rather than a skipped write, so a store from the future
  refuses to open rather than opening wrong.
- **Queries.** A program that verifies against a schema keeps verifying against
  it. Removing a verb, or narrowing what one accepts, is a minor bump and is
  listed in the release. Widening what one accepts is not a break.
- **The prompt.** `theorem.prompt.TUTORIAL` is versioned by its own hash rather
  than by the release. Any change to it changes `fingerprint()`, which is what
  benchmark result files are keyed by, so a number can never silently belong to
  a different prompt.
- **The Python surface.** Everything in `theorem.__all__`. Anything reached
  through a module path (`theorem.engine.executor.Table`) is internal, whatever
  its name suggests.

## Storage

Single process, disaggregated shape preserved: an append-only WAL (`wal.jsonl`, one JSON record per write, position = line number); in-memory state rebuilt on open by replay; `snapshot()` writes an immutable run file `runs/run-<pos>.json` and truncates the WAL. A torn final WAL line (crash mid-append) is recovered by replaying the longest valid prefix. Lineage records live in the WAL and are never pruned.

**One writer.** A store takes an exclusive advisory lock on its directory when it opens. A second opener is refused by name, saying which process holds it; two writers would each assign the same ids and overwrite each other's records. The lock is released when the holding process dies, however it dies, so a crash does not leave a directory unopenable. A tool that only reads an idle directory can opt out with `lock=False`.

**Readers.** A store reads its directory once, at open, so a second process holding it open with `lock=False` answers from the graph as it was. `refresh()` replays what has been committed since and returns how many records that was. Records are selected by the position they carry rather than by a byte offset, so a writer that compacted the log mid-read is not a special case: the run file is newer, and the store is rebuilt from it.

**Compaction.** A snapshot is taken automatically once the WAL passes a threshold, which is both a fixed floor and the current size of the live data. Bounding it below by the data keeps loading a large graph linear: with a fixed threshold alone, a million-node ingest would rewrite a million-record run file on every threshold crossing. Runs older than the newest two are deleted.

**Durability.** A committed record survives the process dying, because the write has reached the operating system. It does not survive the machine losing power: the write path does not fsync. Snapshots do, being rare enough for the guarantee to be free.

**Reads do not write.** Traffic telemetry (`query_traffic`, and the `health` subscores built on it) is counted in memory and reaches disk with the next snapshot. It used to be a WAL record per node per follow, which made every question a write: a read-only workload grew the log forever, answering a question needed write access, and the read path was 7x slower on the benchmark graphs. A crash loses some counts of who looked at what, which is the right thing to lose.

**Limits.** A read runs under a row ceiling and a wall-clock deadline (`theorem.engine.executor.limits`). `budget` bounds the answer that is printed, which does nothing for a traversal that fills memory before it reaches `return`; these bound the work. Exceeding either raises an error naming the ceiling and the clauses that lower the cost.

**Scale.** Everything is in memory, with no spill to disk, at roughly 6.7 KB per node measured on the CypherBench `politics` graph (885k nodes, 5.7 GB). A query's binding table is built on top of that, so the envelope is two thirds of RAM rather than all of it: about 3.4 million nodes on a 32 GB machine. `theorem stats --db <path>` reports where a store sits against it. On the CypherBench `soccer` graph, 275,185 nodes and 1,119,766 edges in 1.7 GB: a lookup by name 0.03 ms, one hop from it 0.03 ms, two hops 0.5 ms, a grouped count over a class 23 ms, a global count 124 ms, and a filter on a property other than `name` 288 ms. Reads write nothing to the log. Only `name` is indexed, so any other filter is a scan of the class, which is the difference between the last two lines and the first three. Exceeding it fails on the next question rather than the next node, which is why the figure has headroom in it.

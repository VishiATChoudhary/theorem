# v0.3: reach, and filtering on an aggregate

Status: design. Supersedes the v0.3 bullets in ROADMAP.md.

## Why these two, and why now

theorem's purpose is graphs built from technical information that is hard to
ingest: bills of materials, dependency trees, standards that cite standards,
org and ownership structures. In every one of those, the questions that matter
are about *reach* rather than about one hop.

- Which components does this assembly transitively contain?
- What breaks if this library changes?
- Does this regulation depend, at any depth, on a clause we have retired?
- Which parts appear in more than three products, so a defect is systemic?

Today theorem can answer none of these. `follow` walks exactly one edge, and
there is no way to filter a group after counting it. Cypher can express both
(`-[:X*1..3]->` and `WITH ... WHERE count > 3`), so these are not places where
theorem is ahead and choosing to stay simple. They are places where it is
behind on the questions its own users have.

Neither capability is measured by CypherBench: of its 2,348 gold queries, zero
use a variable-length pattern, zero use a subquery, and none exceed two hops.
Building them cannot improve that benchmark, which is the point. They are
justified by the use case, and the benchmark is kept as a regression check that
they broke nothing.

## Transitive traversal

```
follow <binding> <edge> <role> upto <N> [where <cond>] as <name>
follow <binding> <edge> <role> upto any [where <cond>] as <name>
```

`upto N` walks the edge between 1 and N times. `upto any` walks until no new
node is reachable. Without `upto`, `follow` is exactly one hop, as today.

The binding names the node **arrived at**, not the path. Intermediate nodes are
not bound, matching what `-[:X*]->` does in Cypher and keeping one name per
line.

`where` filters the arrival node, as it already does. It is applied at every
depth, so a node that fails it is not returned; traversal still continues
through it, because "parts under $5 in this assembly" should not stop at the
first expensive subassembly.

**Termination.** The existing trail rule already gives this for free: an edge
instance is used at most once per result row, so a cycle cannot be walked twice
and traversal always terminates. A graph with cycles needs no special case and
no visited-set bolted on top. This is the main reason `upto` fits theorem
rather than fighting it.

**Cost.** `upto any` on a large graph can touch a lot of nodes. It is bounded
by the number of edges of that type reachable from the seed, and the existing
`budget` on `return` still caps what is serialized. No separate guard.

## Filtering on an aggregate

```
keep <binding> where <cond>
```

`keep` filters the rows that exist at that point in the pipeline. After an
aggregate it filters groups, which is the case that is impossible today:

```
find part as p
follow p used_in whole as product
group by p as g
count distinct g.product as n
keep g where n > 3
return p.name, n
```

Before an aggregate it filters plain rows, which `find ... where` can mostly
already do; `keep` is still allowed there so the rule is one rule.

`keep` is a separate line rather than a clause on the aggregate, because every
other operation in theorem is its own line with its own name, and because
"count, then keep the ones over three" is the order the question is asked in.

## Not in this change

- **Paths as values.** Returning *why* two nodes are connected is a real agent
  need and a bigger design question: it needs a path type, a way to render it
  inside a token budget, and a decision about what a path equals for
  deduplication. It gets its own spec.
- **Depth of a transitive hop.** `upto` does not expose how many hops were
  taken. It is easy to add later as a pseudo-property and there is no evidence
  yet that agents need it; adding it now would be guessing.
- **Shortest path.** Follows from paths as values.

## Compatibility

Both are additions. `upto` and `keep` are new words in positions that were
previously parse errors, and no existing program can contain them. Every
current test must pass unchanged.

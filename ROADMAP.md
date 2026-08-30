# theorem roadmap

Directions, not promises. Comment on the linked issues (or open one) to influence priority.

## v0.2: close the expressiveness gaps (done)

- **Union**: a line containing only `or` starts an alternative branch.
- **Optional traversal**: `follow ... or none` keeps rows whose edge is absent.
- **Edge properties**: `via.<prop>` inside a follow's condition, with `none` for
  values that are missing rather than merely unequal.

## v0.3: what technical graphs need and Cypher already has

Aimed at dependency, bill-of-materials and standards graphs, where the
interesting questions are about reach rather than about one hop:

- **Transitive traversal**: follow an edge repeatedly, bounded or to exhaustion.
  "What transitively depends on this component" has no expression today.
- **Filtering on an aggregate**: keep the groups whose count passes a test,
  without a second query.
- **Path as a value**: return *why* two nodes are connected, not just that they
  are, so an agent can cite the chain.

Each needs a language proposal issue first (see [CONTRIBUTING](CONTRIBUTING.md), spec-first rule).

## v0.x: engine

- Concurrent readers during a write (currently single process, single writer).
- Snapshot compaction and WAL size management for long-lived graphs.
- Faster dedup blocking for graphs beyond 10^6 nodes.
- Import/export: bulk load from CSV/JSONL and from Cypher dumps.

## v0.x: agent ergonomics

- Error-message quality pass: every verifier error should name the fix, not just the problem.
- Session-level schema diffing: tell the agent what changed since it last looked.
- Richer `continue @c...` cursors (seek, sample).

## Research track

- Benchmark expansion beyond the NBA/movies slices; adversarial schema suite.
- Formal grammar spec suitable for alternative engine implementations.
- Multi-agent write contention semantics (receipts already carry provenance; what does conflict look like?).

## Non-goals for now

Distributed execution, a query planner with cost model, Cypher compatibility mode, Bolt protocol support.

# theorem roadmap

Directions, not promises. Comment on the linked issues (or open one) to influence priority.

## v0.2: close the expressiveness gaps

The CypherBench eval deliberately excluded three query categories theorem cannot yet express. They are the top priorities:

- **Union**: combine results of two pipelines (`union` verb, one line, staged like everything else).
- **Optional traversal**: keep rows whose edge is absent (`follow ... optional`), nulls sort last as everywhere.
- **Edge properties**: match and return properties on edges, not just nodes.

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

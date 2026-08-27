# Issues to file at launch

File these the day the repo goes public. Label as noted; first six get `good first issue`.

---

**1. Support a local/OpenAI-compatible endpoint in the eval harness** `good first issue` `benchmark`
The harness shells out to the `claude` CLI (`eval/run_eval.py`). Add a `--endpoint` option that hits any OpenAI-compatible chat API so people can benchmark local models (Llama, Qwen) and non-Anthropic APIs. The prompt is already plain text; this is plumbing, not prompting.

**2. `theorem --version` flag** `good first issue`
The CLI has no version flag. Read the version from package metadata (`importlib.metadata.version("theorem")`) and print it. One function in `src/theorem/cli.py` plus a test.

**3. REPL line editing and history** `good first issue`
The REPL reads raw stdin; arrow keys print escape codes. Importing `readline` on platforms that have it gives editing and history for free. Guard the import for Windows.

**4. Error message audit: every verifier error should name the fix** `good first issue` `dx`
Some verifier errors suggest alternatives (`did you mean: launch_year?`), some only name the problem. Sweep `src/theorem/verifier.py` for error sites without a suggestion and add nearest-alternative hints where a candidate set exists. Each fixed message needs a test asserting the suggestion.

**5. `schema` output should include derived-class status and quotas** `good first issue`
`schema` renders classes and edges but a `derive class` subclass's provisional status and remaining quota are only visible via `find class`. Include them in the `schema` rendering.

**6. Windows CI is untested territory: run and fix** `good first issue` `ci`
The CI matrix includes windows-latest but path handling in `engine/storage.py` and the REPL have never been exercised by a Windows user. Run the suite on Windows, report or fix what breaks.

**7. Language proposal: `union` verb** `language-proposal` `roadmap`
Combine the results of two pipelines. Blocked benchmark category. Needs syntax discussion: staged like everything else, one line, no nesting. Strawman in ROADMAP.md.

**8. Language proposal: optional traversal** `language-proposal` `roadmap`
`follow ... optional` keeping rows whose edge is absent, with null bindings that sort last. Blocked benchmark category.

**9. Language proposal: edge properties** `language-proposal` `roadmap`
Match and return properties on edges. Touches schema declaration, assert edge, follow conditions, and return columns; the largest of the three roadmap proposals.

**10. Bulk import: CSV/JSONL loader** `enhancement`
`eval/load_graph.py` already loads CypherBench JSON into a store; generalize into a documented `theorem import` subcommand for CSV/JSONL with a mapping file.

**11. Snapshot compaction policy** `enhancement` `engine`
`snapshot()` exists but nothing calls it automatically. Design a policy (WAL length threshold?) and wire it into the session, preserving the crash-recovery property tests.

**12. Property-test the dedup pipeline** `testing`
`engine/dedup.py` has example tests only. Hypothesis strategies over near-duplicate name pairs would pin the blocking-key and containment-boost behavior.

---

# From the pre-launch edge-case reviews (not fixed for v0.1.0, tracked)

**13. fsync WAL appends and run files** `engine` `durability`
Acknowledged writes flush userspace buffers but never `os.fsync`; a power cut can drop them. Decide policy (fsync per write vs per block) and benchmark cost.

**14. Multi-record writes (merge/refine/compact) need transaction markers** `engine` `durability`
A crash mid-merge can leave an alias installed with the survivor unmerged; mid-refine leaves partial child sets. Design begin/commit records or single-record composite ops, plus replay-time rollback of unterminated groups.

**15. Lock file / single-writer enforcement** `engine`
Two processes on one db path silently interleave WAL appends and hand out duplicate ids. Add an advisory lock file with a clear error.

**16. `!=` on unset properties returns false** `language-proposal` `semantics`
`where discontinued != true` excludes nodes where the property was never set. Decide and spec explicit null semantics for each operator (current: no operator matches null).

**17. Budget: first result block always emitted, header/truncation text not counted** `engine`
A single oversized row blows the token budget. Reserve header cost and emit a truncation notice instead of an oversized first block.

**18. Cap intermediate binding-table size** `engine`
Cross products materialize fully in memory before budgets apply. Add a row cap with a clear error naming the offending statement.

**19. `after @t-N` is parsed but inert; continuations unbounded** `engine`
Implement the read barrier (or reject the clause until implemented) and add an LRU bound on stored continuations.

**20. Quota bypass via refine; refine not atomic per row; re-refine duplicates children** `engine`
`_quota_check` only runs on assert. Ragged/malformed CSV rows abort refine halfway with children already durable. Refining an already-composite blob mints a second child set.

**21. assert edge discards its `source` provenance** `bug`
`stmt.source` is parsed for edges but never stored.

**22. Aggregate shape gaps: `count g` after value-group, aggregate consuming bindings used later** `verifier`
`group by p.name as g` then `count g as n` hits an IndexError (now caught as internal error, still wrong); `count p as n` then `return p.name` verifies but fails at runtime.

**23. Deep column paths partially validated** `verifier`
`p.health.nope` and `p.name.extra` verify but fail or silently alias at runtime; `where unit_cost > "x"` verifies and matches nothing. Type-check condition literals against declared prop types.

**24. Retired nodes accepted by write verbs; subclass follow checks; duplicate prop keys** `verifier` `engine`
`retire`/`flag`/`merge` accept already-retired targets. `follow` rejects subclass bindings that edge roles accept. Duplicate keys in props/mappings silently keep the last.

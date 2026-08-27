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

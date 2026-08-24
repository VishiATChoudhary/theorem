# GraphLang v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Working v0 of the agent graph DSL (parser, verifier, executor) plus single-process engine (WAL, snapshots, writes, dedup, lineage, health), an eval harness beating text2cypher on a CypherBench slice, and a spider diagram of results.

**Architecture:** Line-oriented DSL compiled to a verified plan, executed over a binding table against an in-process graph store with append-only WAL and immutable snapshot runs (disaggregated shape, one process). Writes return receipts carrying dedup candidates; lineage and health are queryable data.

**Tech Stack:** Python 3.12, uv, pytest, stdlib only for the core (`difflib`, `json`, `threading`); `matplotlib` for the spider diagram; `claude -p` CLI for eval-time LLM generation; optional Neo4j via docker for the Cypher baseline.

**Spec:** `docs/superpowers/specs/2026-08-24-graphlang-v0-design.md`

## Global Constraints

- No em dashes in any output, docs, code comments, or commit messages.
- Core package `graphlang/` uses stdlib only. Eval extras live in `eval/` and may use `matplotlib`.
- Canonical forms: parser accepts exactly one spelling per operation (spec EBNF).
- Verify-before-execute: no partial execution ever; error messages name the line, offer nearest alternatives, end with `nothing was executed.`
- Token counting heuristic everywhere: `len(text) // 4`.
- Default budget 2000 tokens.
- After each task: run `/codex adversarial review` loop (codex:rescue subagent; fallback caveman:cavecrew-reviewer) until zero findings, then commit.
- Commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Scaffold + Tokenizer + Parser + AST

**Files:**
- Create: `pyproject.toml`, `graphlang/__init__.py`, `graphlang/ast_nodes.py`, `graphlang/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces: `parse(text: str) -> list[Stmt]` raising `ParseError(line_no, msg)`. AST dataclasses in `ast_nodes.py`: `Find(target, cond, name, line)`, `Follow(src, edge, role, name, line)`, `GroupBy(col, name, line)`, `Aggregate(op, distinct, col, name, line)`, `Return(cols, order_by, desc, limit, budget, after, line)`, `Continue(handle, budget, line)`, `AssertNode(cls, props, source, name, line)`, `AssertEdge(edge, role_refs, source, line)`, `Merge(a, b, policy, line)`, `Distinct(a, b, reason, line)`, `Refine(ref, into_cls, mapping, name, line)`, `Compact(src, name, props, line)`, `Retire(ref, reason, line)`, `Flag(ref, reason, line)`, `DeriveClass(name, base, props, line)`, `SchemaStmt(line)`. `Col = tuple[str, ...]` (split on `.`). `Cond = list[tuple[str, Clause]]` with joiner `"and"|"or"`, `Clause(col, op, value)`.

- [ ] **Step 1: uv scaffold.** `uv init --lib --name graphlang`, add pytest dev dep, `uv run pytest` runs (0 tests).
- [ ] **Step 2: Write failing parser tests** covering: Q1/Q2 from explainer verbatim, logical-line continuation (indented physical lines), every write verb from explainer Part III verbatim, `schema`, `continue @c81f budget 1500 tokens`, comment lines, and errors (unknown verb, bad props, missing `as`). Sample:

```python
def test_q2_parses():
    stmts = parse(Q2_TEXT)
    assert [type(s).__name__ for s in stmts] == [
        "Find", "Follow", "Follow", "GroupBy", "Aggregate", "Return"]
    g = stmts[3]; assert g.col == ("sups",) and g.name == "g"
    agg = stmts[4]; assert agg.op == "count" and agg.distinct and agg.col == ("g", "parts")
    ret = stmts[5]; assert ret.budget == 2000 and ret.order_by == ("n_parts",)

def test_continuation_lines_join():
    stmts = parse('assert part {name: "x", unit_cost: 12.0}\n  source doc:d/p3 as gs')
    assert type(stmts[0]).__name__ == "AssertNode" and stmts[0].source == "doc:d/p3"
```

- [ ] **Step 3: Run, verify FAIL** (`parse` undefined).
- [ ] **Step 4: Implement.** Regex tokenizer (strings, numbers, ids `#x-1`, `@t-`/`@c` tokens, provenance `doc:`/`attach:`, words, punct `{},():`), logical-line joiner, one `parse_<verb>` function per statement per spec EBNF. No lookahead beyond one token. `ParseError` carries line number of the logical line start.
- [ ] **Step 5: Run tests, PASS.**
- [ ] **Step 6: Adversarial review loop; fix; re-run tests until clean.**
- [ ] **Step 7: Commit** `feat: parser and AST for GraphLang v0`.

### Task 2: Schema + Verifier

**Files:**
- Create: `graphlang/schema.py`, `graphlang/verifier.py`
- Test: `tests/test_verifier.py`

**Interfaces:**
- Consumes: AST from Task 1.
- Produces: `Schema` with `classes: dict[str, ClassDef]` (`ClassDef(name, props: dict[str, str], base: str | None, allowed_states: set[str], status: str)`), `edges: dict[str, EdgeDef]` (`EdgeDef(name, roles: dict[str, str])`, roles maps role name to class name); `Schema.supply_chain()` factory building the running-example schema; `verify(stmts, schema) -> list[Plan]` raising `VerifyError(line_no, msg)` where msg includes `did you mean` suggestions (difflib `get_close_matches`) and ends with `nothing was executed.` Verifier tracks binding env: each name maps to a class (or `"group"`/`"value"`), checks: classes/edges/roles/props exist, `follow` source bound, arrival role differs from source role when classes differ (type error to arrive where you already stand), aggregate consumes a group binding, `return` columns bound, duplicate `as` names rejected.

- [ ] **Step 1: Failing tests**: valid Q2 verifies; `find vendor ...` errors with `did you mean: supplier`; `follow parts supplied_by item` errors as role type error; `count distinct g.parts` without prior group errors; error text ends `nothing was executed.`

```python
def test_unknown_class_suggests():
    with pytest.raises(VerifyError) as e:
        verify(parse('find vendor where name = "x" as v'), Schema.supply_chain())
    assert "did you mean" in str(e.value) and "supplier" in str(e.value)
    assert str(e.value).rstrip().endswith("nothing was executed.")
```

- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS.**
- [ ] **Step 5: Review loop. Step 6: Commit** `feat: schema model and verify-before-execute`.

### Task 3: Storage Engine

**Files:**
- Create: `graphlang/engine/__init__.py`, `graphlang/engine/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `Store(path)` with: `apply(record: dict) -> int` (append WAL, apply to memory, return position); in-memory `nodes: dict[str, Node]` (`Node(id, cls, props, state, created_at, retired_at, aliases, origin, flags, traffic)`), `edges: dict[str, list[Edge]]` incident lists (`Edge(id, type, roles: dict[str, str], created_at, retired_at)`), `lineage: list[dict]`, `distinct_pairs: set[frozenset]`, `dup_ledger: list[dict]`; `resolve(id) -> str` (alias chase); `snapshot()` writes `runs/run-<pos>.json`, truncates WAL; reopen replays run + WAL identically; `next_id(cls) -> str` deterministic `#<cls initial>-<counter>`; positions monotonic across reopen.

- [ ] **Step 1: Failing tests**: apply node/edge records; reopen rebuilds identical state; snapshot then more writes then reopen rebuilds; alias resolve chases chains; positions survive reopen.
- [ ] **Step 2: FAIL. Step 3: Implement** (WAL = jsonl, replay on open, records are pure data: `{"op": "put_node"|"put_edge"|"lineage"|"distinct"|"dup"|"patch_node", ...}`). **Step 4: PASS.**
- [ ] **Step 5: Review loop. Step 6: Commit** `feat: WAL plus snapshot storage engine`.

### Task 4: Read Executor + Serialization + Budgets

**Files:**
- Create: `graphlang/engine/executor.py`, `graphlang/serialize.py`
- Test: `tests/test_executor.py`, `tests/test_serialize.py`

**Interfaces:**
- Consumes: Store (Task 3), verified plans (Task 2).
- Produces: `execute_read(stmts, store, schema, continuations: dict) -> str` building `BindingTable(cols: list[str], rows: list[dict[str, object]])`; group values stored as `GroupedTable(key_col, groups: dict[key, list[row]])`; serialization functions `render_table(...)`, `render_incident(...)` per spec result format; budget enforcement truncates at row boundary and registers `@c<hex>` continuation carrying remaining rows; `continue` statement drains it. Special targets: `find nodes` (any class), `find dup_candidates`, `find class`. `where` clauses evaluate `=` `!=` `>` `>=` `<` `<=` `contains`; `and` binds tighter than `or`. Retired nodes excluded. Order: query-structural (BFS distance from find-anchors, then recency) for incident rendering; explicit `order by` for tabular.

- [ ] **Step 1: Failing tests** on a small fixture graph built via Store records (3 products, 4 parts, 3 suppliers incl. two suppliers sharing a name): Q1 returns 2 supplier names; Q2 groups by identity (same-named suppliers NOT merged, this is the trap test); `group by sups.country` merges by value; budget truncation emits `truncated: K more. resume with: continue @c` and `continue` returns the rest; header declares counts; empty result says `results: 0 of 0, complete`.

```python
def test_group_by_identity_not_name():
    out = run(Q2_TEXT, store_with_two_ionix())
    assert out.count("Ionix") == 2  # two rows, distinct suppliers
```

- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS.**
- [ ] **Step 5: Review loop. Step 6: Commit** `feat: read executor, incident serialization, token budgets`.

### Task 5: Write Surface + Dedup + Lineage + Health

**Files:**
- Create: `graphlang/engine/writes.py`, `graphlang/engine/dedup.py`, `graphlang/engine/health.py`
- Test: `tests/test_writes.py`, `tests/test_dedup.py`, `tests/test_health.py`

**Interfaces:**
- Consumes: Store, Schema, parser AST.
- Produces: `execute_write(stmt, store, schema, env) -> Receipt`; `Receipt.render() -> str` matching explainer receipt format (`receipt: created part gs = #p-88231 at @t-99841`, guards line, dup candidates block with `resolve with: merge / distinct`). `dedup.block_key(cls, name) -> str`; `dedup.sync_candidates(store, node) -> list[Candidate]` (same block, `SequenceMatcher.ratio() >= 0.85`, distinct-suppressed pairs excluded); `dedup.sweep(store)` async-shape maintenance pass (explicit call). `health.scores(store, node_id) -> dict` with keys `loss, query, structure, staleness` per spec formulas; executor (Task 4) exposes them at `health.<sub>` columns and `find nodes where health.loss > 0.8` works. Verbs: assert node (attach:csv payload parsed into `props["_rows"]` from `attachments/<key>.csv`), assert edge, merge (survivor = older; alias; lineage both states; `prefer newest` default, `prefer source <prov>`), distinct, refine (one child per `_rows` row via mapping, origin lineage, blob to `composite`, children dedup-checked and queued), compact (summary node, members retired with lineage), retire, flag (increments node flags), derive class (provisional, quota 500, similar-class note via difflib against existing class names).

- [ ] **Step 1: Failing tests**: assert returns receipt with dup candidate for near-name (`"graphene sheet"` vs `"graphene sheets"` score >= 0.85); merge makes alias resolve and old id queries still work; distinct suppresses the pair from future receipts; refine on csv blob creates N children with origin lineage and blob state `composite`; retire excludes from reads but `find nodes` with no retired filter still excludes (historical read out of v0 scope, retirement is exclusion + record); flag raises `health.query`; supernode (degree > 100 fixture) raises `health.structure`; derive class receipt shows provisional + quota + similar-class note; end-to-end explainer construction session transcript replays with matching receipt shapes.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS.**
- [ ] **Step 5: Review loop. Step 6: Commit** `feat: structural writes, receipts, dedup, lineage, health`.

### Task 6: Session Facade + CLI + End-to-End

**Files:**
- Create: `graphlang/session.py`, `graphlang/cli.py` (entry `python -m graphlang <file.gl>` and `--repl`)
- Test: `tests/test_session.py`

**Interfaces:**
- Produces: `Session(path, schema)` with `run(text: str) -> str` (parse, verify, execute mixed read/write programs, receipts and results concatenated; `schema` statement prints schema in explainer format; verifier env threads write bindings `as gs` into later statements). This is the single entry the eval harness uses.

- [ ] **Step 1: Failing test**: full explainer end-to-end session (schema, assert supplier with dup candidate, merge, assert blob, health worklist, refine) as one integration test asserting key receipt lines.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS.**
- [ ] **Step 5: Review loop. Step 6: Commit** `feat: session facade and CLI`.

### Task 7: Eval Harness + Benchmark

**Files:**
- Create: `eval/fetch_cypherbench.py`, `eval/load_graph.py`, `eval/prompts.py`, `eval/run_eval.py`, `eval/README.md`
- Test: `tests/test_eval_load.py` (loader only; LLM calls not unit-tested)

**Interfaces:**
- Consumes: `Session` (Task 6).
- Produces: `fetch_cypherbench.py` downloads one CypherBench domain graph + questions (HF `megagonlabs/cypherbench`, fallback GitHub raw); `load_graph.py: load(graph_json, session)` derives Schema from the graph's schema section (role names generated as `subj`/`obj` semantic names from relation names, deterministic rule documented in eval/README.md) and bulk-loads nodes/edges through Store records; `prompts.py` builds (A) text2cypher prompt (schema + question, matching CypherBench format) and (B) GraphLang grammar prompt (compact EBNF from spec + 6 worked examples + schema); `run_eval.py` runs N>=40 stratified questions through `claude -p --model haiku`, executes condition B on Session, condition A on Neo4j via docker if `docker info` succeeds else records published-baseline mode, scores execution accuracy (normalized set compare vs gold answers), writes `eval/out/results.json` with per-slice numbers (overall, multi-hop, 1-hop, syntax-validity rate, mean result tokens).

- [ ] **Step 1: Failing loader test** on a checked-in mini-fixture graph JSON.
- [ ] **Step 2: FAIL. Step 3: Implement loader. Step 4: PASS.**
- [ ] **Step 5: Implement fetch + prompts + runner; smoke-run 3 questions; then full run.**
- [ ] **Step 6: Review loop (harness code + scoring honesty). Step 7: Commit** `feat: CypherBench eval harness and results`.

### Task 8: Spider Diagram + Final Report

**Files:**
- Create: `eval/spider.py`, `eval/out/spider.png`, `README.md` (project readme with results table)

**Interfaces:**
- Consumes: `eval/out/results.json`.
- Produces: radar chart, axes: overall EX, multi-hop EX, 1-hop EX, syntax validity, token economy (normalized inverse of mean result tokens); two series (GraphLang, text2cypher baseline). MUST invoke dataviz skill before writing chart code.

- [ ] **Step 1: Invoke dataviz skill. Step 2: Implement `spider.py`, generate PNG. Step 3: README with results + diagram. Step 4: Review loop. Step 5: Commit** `feat: results spider diagram and readme`.

## Self-Review Notes

- Spec coverage: grammar (T1), verify-before-execute + suggestions (T2), storage shape D15/16 (T3), budgets/continuation D13, ordering D14, identity-grouping trap (T4), writes/receipts/dedup D8-10, granularity D5-6, lineage D7, health D11-12 (T5), two-tier surface is documentation-level (prompts in T7 teach core verbs only for reads), eval + success claim (T7), spider (T8). Decision 3 constrained decoding: parse-time validation only in v0, per spec.
- Type consistency: `Session.run` is the only cross-boundary surface for eval; AST names fixed in T1 and reused verbatim in T2/T4/T5.
- Known deferrals (documented in spec): promotion gating, `after` barrier semantics beyond parse, real embeddings, historical reads of retired nodes.

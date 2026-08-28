# Playbooks: natural-language use cases compiled to theorem schemas

Date: 2026-08-28
Status: draft for review
Parent spec: `2026-08-28-ingestion-design.md` (playbooks are its schema-source answer)

## Concept

A **playbook** is a natural-language markdown file in which a customer describes a use case: what they track, what matters to them, and the rules of their domain. An agent compiles it into a theorem program of schema declarations; after approval the schema is live, durable, and carries lineage back to the playbook that motivated it.

Decisions locked with the user:

- Scope: playbooks control **schema + extraction focus + policies** (quotas, dedup thresholds). Not just classes.
- Lifecycle: **one active playbook per database** in v0. Playbooks are use-case specific; the long-term direction is one database per playbook and enterprise-level connection ACROSS those databases (out of scope here, but nothing may preclude it).
- Approval: **guided by default** (show program + summary, confirm, apply); a `--unhinged` flag auto-applies everything and shows receipts after.

## The playbook file

Freeform markdown. A recommended (not required) structure the compiler prompt teaches:

```markdown
# Competitor intelligence

## What we track
Companies that compete with us, their products, product pricing,
and which suppliers they source from.

## What matters
Launch dates and price changes are critical. Ignore press-release
fluff and legal boilerplate.

## Rules
A company is the same company regardless of legal suffix (GmbH, Inc).
We never track individuals. Keep at most ~50 competitors.
```

Everything is prose. The compiler, not the customer, translates it into typed declarations.

## Compilation target: the language itself

The compiler emits a **theorem program**, not a config file, so schema creation gets verify-before-execute, receipts, WAL durability (already landed for `derive class`), and lineage, with zero new machinery beyond the verbs below.

### Language additions

1. **Built-in root class** `entity {name: str}` in every schema. Playbook classes derive from `entity` or from each other. (`document`/`chunk`/`media`/`piece`/`table_blob` remain the ingestion built-ins; playbook classes never derive from those.)
2. **`derive edge`** (new verb), the missing sibling of `derive class`:
   ```
   derive edge supplied_by(item: competitor_product, source: supplier)
   ```
   Grammar: `"derive" "edge" NAME "(" ROLENAME ":" CLASSNAME "," ROLENAME ":" CLASSNAME ")"`. Verified like edge definitions (exactly two roles, known classes); durable via a `derive_edge` lineage record replayed at session start, same mechanism as classes.
3. **Policy clauses on `derive class`** (optional, ordered):
   ```
   derive class competitor from entity with {hq_country: str} quota 50 dedup 0.9
   ```
   - `quota N`: instance cap (mechanism exists; today it is hardcoded to 500 for provisional classes; this makes it declarable).
   - `dedup X`: per-class similarity threshold overriding the global 0.85 (new field on ClassDef, read by the dedup pipeline).
   Policy set is deliberately v0-minimal. Retention/staleness policies and per-class health tuning are named future work, not designed here.

### Extraction focus

The "what matters" prose does not compile to syntax. It is stored verbatim as a `focus` property on the playbook's document node and is injected into every stage-3 extraction prompt for this database ("prioritize: ...; ignore: ..."). Focus is guidance for the extracting agent, never enforcement; enforcement is the schema.

## Compile flow

```
theorem playbook compile playbook.md --db ./db --agent claude [--unhinged]
```

1. Playbook file ingests as a `document` node (normalize + stage from the parent spec), sha256-deduped.
2. Compiler prompt = playbook text + current live `schema` rendering + the derive-verb grammar with worked examples.
3. Agent (via the pluggable Runner) emits: (a) a theorem program of `derive class` / `derive edge` statements, (b) a plain-language summary including assumptions it made where the playbook was ambiguous, (c) the extraction-focus text.
4. Program is verified whole. VerifyError -> corrective error fed back, one repair retry (the standard loop).
5. **Guided (default):** program + summary printed, user confirms, program executes, receipts shown. **Unhinged (`--unhinged`):** skip confirmation, execute, show receipts. Same path in the demo UI: a playbook upload pane with a proposed-schema panel and an Apply button (or the unhinged toggle).
6. Every derived class/edge records lineage `{kind: derive_class|derive_edge, playbook: <document id>}`, so `why does class X exist` is answerable by query, and the playbook document's provenance covers the whole schema.

## Recompile (playbook edited)

v0 keeps this deliberately small:

- Re-running compile on an edited playbook diffs proposed schema against live schema.
- New classes/edges: added (guided approval as above).
- Removed classes: **deprecated, never deleted**: class status moves to `deprecated`, existing nodes stay queryable, new `assert`s are verifier-rejected with an error naming the playbook change. (New status value on ClassDef; one verifier check.)
- Changed property sets: additive changes apply; removals deprecate the property in the class definition (props kept on existing nodes; verifier rejects new writes to it).
- No data migration verbs in v0. `refine`/`compact`/`merge` already cover manual reshaping.

## Future: enterprise, multiple playbooks

Direction (recorded, not designed): each playbook owns its database; an enterprise layer connects databases, with cross-db queries resolving entity overlap through the dedup/merge machinery. Two consequences for v0 design: (1) playbook identity must be stable (the playbook document node id + sha256 history is that identity); (2) nothing in the schema may assume global uniqueness beyond one database.

## Failure modes and mitigations

- Agent emits invalid derive syntax: verifier catches, corrective error, one retry, then fail loudly with the raw program shown.
- Agent invents classes the playbook never asked for: guided approval is the gate; the summary must justify each class with a quote from the playbook (prompt requirement), making padding visible.
- Ambiguous playbook: compiler states assumptions in the summary rather than asking questions in v0.
- Unhinged mode misfires: everything it did is receipts + lineage; `retire`/deprecation undoes it. Documented as the tradeoff of the flag.

## Testing

- Unit: `derive edge` parse/verify/execute/replay; policy clauses land on ClassDef; per-class dedup threshold honored by the pipeline; deprecated classes reject asserts.
- Golden: three playbook fixtures (competitor intel, research-lab inventory, deliberately ambiguous one-liner) with recorded compiler outputs; compile is runner-mocked in CI (no API calls).
- Property: recompile with an unchanged playbook is a no-op (idempotence).

## Build order

1. `entity` root class + `derive edge` verb + durable replay (engine, no agent involvement).
2. Policy clauses (`quota`, `dedup`) on `derive class`, per-class threshold in dedup pipeline.
3. Deprecation status + verifier checks.
4. Compiler prompt + Runner integration + guided/unhinged CLI flow.
5. Demo UI pane.

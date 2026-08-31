# theorem roadmap

Directions, not promises. Every open item states the number that closes it,
because an objective without an exit criterion is a mood.

## Shipped

**v0.2: expressiveness.** `or` branches (union), `or none` (optional follow),
`via.<prop>` with `none` (edge properties), `upto N` / `upto any` (transitive
reach), `keep <b> where <cond>` (filter after aggregating), `return distinct`,
name reuse as a join. All are in the [language spec](docs/language-spec.md) and
the [tutorial](docs/tutorial.md), and a CI test fails when a verb the parser
accepts is missing from either.

**v0.2: production floor.** One writer per store, enforced by an advisory lock
that a crash releases. Automatic WAL compaction, amortized so a large ingest
stays linear. A row and wall-clock ceiling on every read. Reads no longer write:
traffic telemetry lives in memory, which took an ordinary query from 129 ms and
4,178 WAL records to 17 ms and none. `theorem load` for CSV and JSONL. An import
surface (`from theorem import Session, Schema, agent_prompt`) and a CLI that can
open a database without the demo schema.

**v0.2: the prompt ships.** The tutorial an agent is given lived in the
benchmark harness, so every published number described a prompt no user had. It
is `theorem.prompt` now, versioned by its own hash, and the harness re-exports
it.

## Open: prove it is better

**Turn the agent-loop tie into a measured result.** At n=120 the interval is six
points wide and the arms sit at 87.5 each, McNemar p = 1.000. Nothing subtle is
measurable there.
*Closes at* n >= 480 across four train graphs, with paired McNemar reported
whatever it says.

**Errors that teach, measured on tokens.** Six verifier and parser messages now
state the rule they enforce rather than only the violation, because both failed
prompt cuts failed specifically at repair. That is a hypothesis until it is
tested.
*Closes at* the tutorial back under 900 tokens with solve@3 no worse than 87.5,
which would take the agent-loop token gap from 2.5x to about 1.9x.

**Token crossover: measured, and it holds.** theorem costs 39 tokens per class
against text2cypher's 85, on top of 1,357 tokens of tutorial that never grows.
The lines cross at 31 classes, and the crossing is inside the measured range:
on the seven benchmark schemas unioned (40 classes, 62 edge types) theorem's
prompt is *smaller*, 2,793 tokens against 3,186. The benchmark graphs have 9 to
13 classes each, which is theorem's worst region.
See [prompt cost](docs/benchmarks/prompt-cost.md). What is still open is
accuracy at that size: nothing has been run against a 40-class graph.

**Check the thesis against a frontier model.** Every result is one small model.
If the gap closes on a frontier model, the language is scaffolding for weak
models and the moat has an expiry date.
*Closes at* both arms, >= 500 questions, one frontier model, published either
way.

## Open: engine

- Automatic refresh. A reader opened with `lock=False` can call `refresh()` to
  catch up with a writer, but has to know to call it; there is no notification
  and no way to read a consistent snapshot while one is in progress.
- Spill to disk. Everything is in memory at ~6.7 KB per node, so a 32 GB machine
  holds 2-4 M nodes and the next node fails.
- Faster dedup blocking beyond 10^6 nodes.
- Import from a Cypher dump, so migrating does not mean re-exporting.

## Open: expressiveness, with evidence

Sampled from what the shipped prompt generates on the CypherBench test set,
after the qualified-condition widening took verification from 93.8% to 97.9%.
Seven failures remain in ~330 questions, in two classes.

**Comparing two bindings' properties.** `keep c where birth_loc.name =
death_loc.name` is rejected: a condition's right-hand side must be a literal.
The question family ("born and died in the same place", "lakes in the same
country as X") is common and the workaround, `compute a.x same b.y as flag`
then `keep c where flag = true`, is not what anyone writes first. A dotted
right-hand side is unambiguous, since literals are never dotted, so this is a
widening rather than a new concept. Needs a language proposal issue first
(CONTRIBUTING's spec-first rule).

**Role guessing on same-class edges.** A model writes `follow p hasHeadOfState
subj` where the schema declares `country` and `politician`, or `follow c
hasMother character` where it declares `subj` and `obj`. The error lists the
roles, so a repair turn fixes it and the agent loop is unaffected; single-shot
loses the question. Accepting `subj`/`obj` as positional aliases for an edge's
two declared roles would fix it and would cost the canonical-form rule that
there is exactly one spelling per operation. Not obviously worth it: four
questions in 330.

## Open: agent ergonomics

- Session-level schema diffing: tell the agent what changed since it last looked.
- Richer `continue @c...` cursors (seek, sample).
- Role naming as a checkable property. The one mistake the verifier cannot catch
  is a reversed role on an edge whose two roles hold the same class
  ([silent-failure benchmark](docs/benchmarks/silent-failure.md)). Nothing in the
  schema distinguishes `subj` from `obj`; a schema that named them `child` and
  `father` would make the mistake visible to the model, if not to the verifier.

- A canonical printer. Two correct answers to the same question are the same
  parsed program, but the language accepts one redundant spelling (a condition
  qualified by its own binding) and normalizes it in the parser, so equality
  holds of the tree and not of the text. Rendering a program back to canonical
  text would let a cache key on a string again.

## Research track

- Adversarial schema suite: near-miss class names, overloaded edge labels.
- Formal grammar spec sufficient for a second engine implementation.
- Multi-agent write contention semantics (receipts already carry provenance;
  what does a conflict look like?).

## Non-goals for now

Distributed execution, a query planner with a cost model, Cypher compatibility
mode, Bolt protocol support.

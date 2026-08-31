# Benchmarks

The current results live in **[benchmarks/cypherbench.md](benchmarks/cypherbench.md)**, which is generated from the result JSONs so it cannot drift from the data.

## Headline

On the full public CypherBench test set, all 2,348 questions, the small Haiku model writing theorem reaches **78.0%** execution accuracy where the same model writing Cypher reaches **70.4%**, ahead on all seven graphs.

That page carries the full method, per-graph and per-category breakdowns, the token and latency comparison, and the caveats that matter, including the prompt asymmetry between the two arms and the fact that theorem's prompt was written against the `nba` graph.

## The other three

Execution accuracy is one question of four, and the other three are measured on their own pages.

- **[Agent loop](benchmarks/agent-loop.md)** &mdash; does it converge under retry, in how many turns, for how many tokens, on graphs nothing was tuned on? Held out by construction: CypherBench's train split shares no schema, question or qid with the test set. On solve rate the two arms are **tied** (McNemar p = 0.392); the difference is in the first attempt, 82.9% against 72.1%.
- **[Frontier model](benchmarks/frontier.md)** &mdash; does the gap survive a model that writes Cypher well? On a seeded stratified sample of 498 questions with Sonnet 5, theorem 74.1% against 64.3%, paired p = 0.0001.
- **[Prompt cost](benchmarks/prompt-cost.md)** &mdash; what does a question cost to ask? theorem carries a tutorial the model has never seen, which is a fixed cost, against a schema render that is cheaper per class. The lines cross at 31 classes.

## Not a benchmark

[What happens to a broken query](benchmarks/silent-failure.md) reports that theorem
refuses 1,811 of 1,928 mutated queries and Cypher refuses none of 1,997. **That
comparison is definitional and should not be quoted as a result.** theorem verifies
against the schema before executing; Cypher has no such step; the two numbers follow
from the language definitions rather than from running anything. The mutations are
ours as well, chosen rather than sampled from real model errors.

The page is kept because the theorem column is a self-audit that found a real blind
spot: 6.1% of our own broken queries still run and return an answer, all of them
reversed direction on an edge whose two roles hold the same class. That is the honest
ceiling on the "can't get wrong" claim.

## How these numbers were produced

[A report on the 31 August 2026 benchmarking session](https://github.com/VishiATChoudhary/theorem/blob/main/docs/report/2026-08-31-benchmarking.md)
covers all four benchmarks, the guards that keep them honest, the eight defects
found in shipped code, and the four found in the benchmark harness, two of which
would have published a spectacular false result. It also records the finding
that made the session necessary: the previously published headline could not be
reproduced by the code that shipped it.

## Changing the engine without moving the numbers

Published results are a property of a version of the code, so an engine change
can move them without anyone noticing. `eval/verify_replay.py` re-executes the
exact queries that were scored, against the exact stores they were scored on,
and reports any question whose score moved. It generates nothing and calls no
model, so it costs minutes rather than hours.

```bash
uv run python -m eval.verify_replay            # against the current published run
uv run python -m eval.verify_replay --queries <frozen.json> --published <dir>
```

The second form compares against an archived run, which is how an engine change
is separated from a prompt change: same queries, same stores, only the code
differs. Every engine change in v0.2 was checked this way across all 2,348
questions.

The prompt is guarded differently. Frozen query files are named by the hash of
the tutorial that produced them, and each scored graph records that hash beside
its results, so a report cannot describe a prompt it never ran. Editing the
prompt invalidates the frozen file by design: a stale one is not found rather
than silently scored.

## A note on the prompt version

The 78.0% above was regenerated in August 2026 against prompt fingerprint
`eb0f4010`, the tutorial the package ships. The figure published before it,
78.02%, came from `3ad56b1c`, a tutorial roughly twice as long that was halved
afterwards and validated only on the agent loop, where a repair turn can hide a
regression that one-shot translation cannot. The frozen-query fingerprint is
what surfaced the mismatch: a query file generated from one tutorial is simply
not found when another is checked out.

Regenerating moved the full-set figure by 0.04 points, 78.02% to 77.98%, and
left the held-out figure unchanged at 76.85%. It did not start there. Sampling
the first generations found the shorter prompt verifying 93.8% where the longer
one verified 97.8% on the same questions, almost all of it one rejected
spelling: `follow c locatedIn lake as l where l.area_km2 < 390000`, which means
exactly what the accepted form means. The language now accepts it, which took
verification back to 97.9% without touching the prompt.

## A note on earlier numbers

An earlier version of this page reported 98.3% for theorem against 73.3% for text2cypher, and 96% against 56% on multi-hop. Those came from a 60-question hand-picked slice of the `nba` graph with the categories theorem could not then express removed, and with a prompt that had been iterated against those same questions. They did not survive the full public benchmark and should not be quoted. The numbers above are the whole test set with nothing excluded.

# Benchmarks

The current results live in **[benchmarks/cypherbench.md](benchmarks/cypherbench.md)**, which is generated from the result JSONs so it cannot drift from the data.

## Headline

On the full public CypherBench test set, all 2,348 questions, the small Haiku model writing theorem reaches **78.0%** execution accuracy where the same model writing Cypher reaches **70.4%**, ahead on all seven graphs.

That page carries the full method, per-graph and per-category breakdowns, the token and latency comparison, and the caveats that matter, including the prompt asymmetry between the two arms and the fact that theorem's prompt was written against the `nba` graph.

## The other three

Execution accuracy is one question of four, and the other three are measured on their own pages.

- **[Agent loop](benchmarks/agent-loop.md)** &mdash; does it converge under retry, in how many turns, for how many tokens, on graphs nothing was tuned on? Held out by construction: CypherBench's train split shares no schema, question or qid with the test set.
- **[Silent failure](benchmarks/silent-failure.md)** &mdash; when a query is wrong, does the caller find out? Break a correct query one token and record what comes back. theorem refuses 1,811 of 1,928 mutants; text2cypher refuses none of 1,997.
- **[Prompt cost](benchmarks/prompt-cost.md)** &mdash; what does a question cost to ask? theorem carries a tutorial the model has never seen, which is a fixed cost, against a schema render that is cheaper per class. The lines cross at 31 classes.

## A note on earlier numbers

An earlier version of this page reported 98.3% for theorem against 73.3% for text2cypher, and 96% against 56% on multi-hop. Those came from a 60-question hand-picked slice of the `nba` graph with the categories theorem could not then express removed, and with a prompt that had been iterated against those same questions. They did not survive the full public benchmark and should not be quoted. The numbers above are the whole test set with nothing excluded.

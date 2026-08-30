# Benchmarks

The current results live in **[benchmarks/cypherbench.md](benchmarks/cypherbench.md)**, which is generated from the result JSONs so it cannot drift from the data.

## Headline

On the full public CypherBench test set, all 2,348 questions, the small Haiku model writing theorem reaches **78.0%** execution accuracy where the same model writing Cypher reaches **70.4%**, ahead on all seven graphs.

That page carries the full method, per-graph and per-category breakdowns, the token and latency comparison, and the caveats that matter, including the prompt asymmetry between the two arms and the fact that theorem's prompt was written against the `nba` graph.

## A note on earlier numbers

An earlier version of this page reported 98.3% for theorem against 73.3% for text2cypher, and 96% against 56% on multi-hop. Those came from a 60-question hand-picked slice of the `nba` graph with the categories theorem could not then express removed, and with a prompt that had been iterated against those same questions. They did not survive the full public benchmark and should not be quoted. The numbers above are the whole test set with nothing excluded.

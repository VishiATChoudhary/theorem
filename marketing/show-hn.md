# Show HN

*URL post to the repo. Best window: Tue-Thu, 8-10am US Pacific. Post the first comment immediately.*

## Title

Show HN: Theorem – a graph query language LLM agents can't get wrong

*(HN capitalizes titles; the lowercase brand survives everywhere else)*

## First comment

Hi HN, author here.

I built this after watching agents fail at Cypher in the same four ways over and over: reversed direction arrows (still-valid queries about the wrong question), hallucinated labels, implicit grouping, and unbalanced long-range syntax. Published benchmarks say frontier models get 40-50% of Cypher wrong on realistic schemas, and the number hasn't moved in two model generations, because accuracy tracks corpus familiarity and your schema is never in the corpus.

theorem makes those failures unrepresentable or loud:

- Edges traverse by role name (`follow parts supplied_by source as sups`); there are no direction glyphs to reverse. A wrong role is a type error.
- One line, one step, one binding. Grouping is its own statement, so adding a return column can't change aggregation semantics.
- The whole program is verified against the live schema before anything runs. Errors name the line, suggest the nearest valid alternative, and state "nothing was executed."
- Results are token-budgeted with explicit truncation and continuation handles, because agent context is the scarce resource.

On a CypherBench slice (60 questions, same model both sides, one repair retry, baseline executed live on Neo4j), Haiku 4.5 goes from 73.3% execution accuracy writing Cypher to 98.3% writing theorem; multi-hop goes 56% → 96%. The result I find most damning for "wait for better models": Sonnet 5 writing Cypher is no better than Haiku writing Cypher.

There's also a write surface designed for agents building graphs, which no existing query language has: every write returns a receipt with dedup candidates found at write time, merge/distinct is an explicit dialogue with full lineage, and per-node health is queryable (`find nodes where health.loss > 0.8`).

Caveats, because they matter: 60-question slice, one domain, union/optional-match/edge-property questions excluded (v0 can't express them; they're the top of the roadmap), single-process Python engine. This is a v0 with a strong signal, not a production database.

Apache-2.0, spec-first governance (language changes are proposal issues before syntax lands), no CLA. The benchmark harness reruns on any model in one command, and runs on models I don't have access to are the contribution I want most.

Happy to answer anything about the design decisions; several were forced by benchmark failures and the spec documents each reversal.

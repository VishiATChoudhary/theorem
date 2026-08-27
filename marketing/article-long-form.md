# LLMs can't write Cypher. So I built a language they can't get wrong.

*Canonical long-form piece. Publish on Substack first, cross-post to Medium and dev.to with canonical URL set. ~1,800 words.*

---

Last year I watched an AI agent confidently query a knowledge graph and return the wrong answer. Not a crash. Not an error. A plausible, well-formatted, wrong answer. The Cypher it wrote was syntactically valid, executed cleanly, and traversed an edge backwards.

Nobody noticed for a week.

That failure mode turns out to be the norm, not the exception. On realistic schemas, LLMs get roughly 40% of Cypher queries wrong. CypherBench measured Claude 3.5 Sonnet at 61.6% execution accuracy and GPT-4o at 60.2%. And here is the part that should worry you if your plan is "wait for better models": two model generations later, Claude Opus 4.8 and GPT-5.5 score 51-58% on the same task family, falling to 19-44% on hard queries. Scaling has had two years. The number has not moved.

So I built theorem: a graph query and construction language designed for the failure modes agents actually have, with its own engine. This week it went open source under Apache-2.0. Here is the argument, the design, and the numbers.

## Why models fail at Cypher, specifically

When you categorize the failures, four structural patterns account for most of the damage:

**Reversed arrows.** Cypher encodes edge direction with ASCII art: `(a)-[:SUPPLIES]->(b)` versus `(a)<-[:SUPPLIES]-(b)`. Models flip these constantly, and a flipped arrow is not an error. It is a valid query about a different question, usually returning a confident empty set.

**Hallucinated schema.** The model has seen a million schemas on GitHub. Yours is not one of them. It writes `:Company` when your graph says `:Organization`, and Cypher happily matches zero nodes.

**Implicit grouping.** Cypher's aggregation grouping is implicit in the return clause: which columns you return silently determines the GROUP BY. Adding one output column changes the semantics of the whole query. Humans get this wrong too.

**Long-range syntax.** Brackets, parens, and braces that open early and close late. Models lose track across clause boundaries.

The important observation: these are all language design problems. None of them is a knowledge problem. The model knows which entities it wants and which relationship connects them. The notation is where correctness dies.

## The corpus argument

There is a deeper reason to believe scaling will not fix this, and it comes from the field's own benchmarks. Text2GraphQuery-Bench found that a fine-tuned 8-billion-parameter model matches or beats the newest frontier models at graph query generation. Capacity is not the bottleneck; corpus familiarity is. Query-language accuracy tracks training-corpus size, not language quality, which is why GQL, the new ISO standard, benchmarks worse than Cypher despite being a cleaner language.

Follow that logic one step further. Even a model that has memorized every public Cypher query has never seen your production schema, because your schema is not in the corpus and never will be. Schema hallucination is a per-deployment problem that pretraining cannot remove.

Which suggests a different attack: stop fighting the corpus and make correctness structural. Derive the vocabulary of legal classes, edges, roles, and properties from the live schema, and verify the entire program against it before anything executes.

## What theorem looks like

Here is a real query: which suppliers provide the most distinct parts for products launched after 2024?

```
find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts desc budget 2000 tokens
```

Each design rule maps to a failure mode:

- **No direction glyphs.** Edges declare two named roles: `supplied_by(item: part, source: supplier)`. You traverse by naming the role you arrive at. There is nothing to reverse; a wrong role is a type error caught before execution.
- **One line, one step, one name.** No nesting, no chaining, nothing to balance across lines.
- **Staged aggregation.** Grouping is its own statement. Adding a return column cannot change the grouping, because the grouping happened two lines earlier. Grouping by identity (`group by sups`) and by value (`group by sups.country`) are visibly different spellings.
- **Verify before execute.** The whole program is checked against the live schema first. A typo gets: `error: unknown property "lunch_year" on class product. did you mean: launch_year? nothing was executed.` The agent repairs and retries. Partial execution never happens.
- **Token budgets.** `budget 2000 tokens` caps the serialized result, with explicit truncation and a continuation handle. Result-size economics are a database property, not a prompt-engineering afterthought.

## The numbers

I evaluated on a CypherBench slice: 60 questions, stratified by hop count, same model and same repair budget in both conditions. The baseline is text2cypher executed live on Neo4j. Full harness is in the repo.

| Condition | Overall EX | Multi-hop |
|-----------|-----------:|----------:|
| theorem + Haiku 4.5 | **98.3%** | **96.0%** |
| text2cypher + Haiku 4.5 | 73.3% | 56.0% |
| theorem + Sonnet 5 | **95.0%** | **92.0%** |
| text2cypher + Sonnet 5 | 71.7% | 60.0% |

Two things in that table matter more than the headline.

First, the scaling row: Sonnet 5 writing Cypher is no better than the far smaller Haiku 4.5 writing Cypher. That is the flat scaling curve, reproduced live. Meanwhile the language switch moves both models 20+ points overall and 30+ on multi-hop.

Second, the economics run backwards from what you would expect: the small cheap model with the right language beats the frontier model with the wrong one, 98.3% versus 71.7%. Agent fleets run on small models because they issue thousands of queries. A language that moves reliable graph access down-market is worth more than a frontier model that matches it at many times the price.

Honest caveats: this is a 60-question slice of one domain graph. Questions requiring union, optional-match, or edge properties were excluded because theorem v0 cannot express them yet (they are the top of the roadmap). The engine is single-process. This is a v0 with a strong signal, not a finished result. The eval loop also changed the language three times: global aggregates, trail semantics, and the compute verb all came out of benchmark failures.

## The half nobody builds: writes

Query generation is the famous problem, but agents also have to *build* graphs, and existing query languages give a construction agent nothing. Every theorem write returns a receipt: the created id, its position, the guards that ran, and any duplicate candidates detected at write time. Dedup is built into the write path. Merging is an explicit dialogue with lineage that records both pre-merge states. There are granularity verbs (refine a blob into typed children, compact a node set into a summary), temporal retirement, and queryable per-node health: `find nodes where health.loss > 0.8`.

The 2026 agent-memory landscape suggests why this surface matters: Mem0 removed its graph variant after finding it lost on recall while running slower at twice the token cost. Those are write-surface and economics failures. Model quality does not touch them.

## And if models do get perfect?

Suppose I am wrong and some future model writes flawless Cypher. Two things survive that outcome.

The error profile argument: benchmarks show that as generation improves, syntax errors vanish and the error mass shifts to semantic mistakes, precisely the ones that execute silently. A language where those mistakes are inexpressible or loud is more valuable next to a stronger model, not less.

The canonicality argument: theorem has exactly one spelling per operation. Correct agents therefore produce byte-identical queries, which makes plan caching trivial and agent behavior auditable. The better the models, the more of their output you can cache and verify, but only in a language canonical enough for equality to mean something.

## It's open source, and the language grows spec-first

theorem is Apache-2.0, DCO, no CLA. The language evolves through proposal issues before syntax lands, so design arguments happen in the open and the spec stays normative. The next expressiveness targets (union, optional traversal, edge properties) are on the roadmap with the benchmark categories they unlock.

If you are building agents on graphs, I want your failure cases. If you work on query languages, I want your objections. And if you want to run the benchmark on another model, the harness is one command.

**github.com/VishiATChoudhary/theorem** · `pip install theorem`

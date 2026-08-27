# r/programming

*Link post to the long-form article (or repo). Title options + first comment. Angle: language design.*

## Title (pick one)

1. I designed a graph query language around LLM failure modes instead of waiting for better models. 56% → 96% on multi-hop queries with the same model.
2. theorem: a graph query language where reversed edges, hallucinated schema, and implicit grouping are unrepresentable

## First comment (post immediately after submitting)

Author here. The short version:

LLMs get ~40% of Cypher wrong on realistic schemas, and the failures are structural: reversed direction arrows (still-valid queries about the wrong question), hallucinated labels, implicit GROUP BY semantics, long-range brackets. Two model generations of scaling haven't moved the number, so I treated it as a language design problem instead.

Design choices, each mapped to a failure mode:

- Edges declare two named roles (`supplied_by(item: part, source: supplier)`); you traverse by naming the arrival role. Direction glyphs don't exist, so they can't be reversed.
- One statement per line, one binding per statement. No nesting, nothing to balance.
- Grouping is its own statement, so return columns can't silently change aggregation semantics (Cypher's implicit grouping bites humans too).
- The whole program verifies against the live schema before anything executes. Typos get a did-you-mean and a guarantee that nothing ran.
- Exactly one spelling per operation, so correct programs are byte-identical: plan caching and auditing come free.

Benchmark: CypherBench slice, 60 questions, both conditions same model with one repair retry, text2cypher executed live on Neo4j. theorem+Haiku: 98.3% overall / 96% multi-hop. text2cypher+Haiku: 73.3% / 56%. Interestingly Sonnet 5 writing Cypher was no better than Haiku writing Cypher (71.7% vs 73.3%), which is the flat-scaling story in one line.

Caveats: one domain, union/optional-match/edge-properties excluded (v0 can't express them yet, they're the roadmap), single-process engine written in Python.

The part I'd most like this crowd's opinion on: the language is deliberately anti-expressive (no composition, no nesting, word operators only). For an agent target audience I think that's right. For humans it's clearly worse to write. Is a language designed for machine writers and human *reviewers* a legitimate design point, or a dead end?

Repo + spec + harness: github.com/VishiATChoudhary/theorem

# lobste.rs

*URL post to the repo. Tags: `plt`, `databases`, `ai`. lobste.rs strongly prefers technical depth and dislikes launch language; the authored-by checkbox marks it as your own work.*

## Title

theorem: a graph query language designed around LLM failure modes (role-named traversal, whole-program schema verification)

## Comment (as author, post after submitting)

The design brief was: LLMs get ~40% of Cypher wrong on realistic schemas, the errors are structural (reversed direction glyphs, hallucinated schema, implicit grouping), and two model generations haven't moved the number. So treat it as a PL design problem.

The interesting design points for this crowd:

- Direction doesn't exist. Edge types declare two named roles; traversal names the arrival role. The class of reversed-edge bugs is unrepresentable, and role misuse is a verify-time type error.
- Aggregation is staged and explicit (`group by g` is a statement, aggregates consume the group binding). Cypher's implicit grouping, where the return clause determines GROUP BY, is the single nastiest silent-failure generator we measured.
- Whole-program verification against the live schema before any execution, with corrective errors ("did you mean launch_year? nothing was executed"). The one-repair-retry loop converges because errors are actionable.
- Exactly one spelling per operation. Correct generators emit byte-identical programs, so caching and auditing reduce to string equality.
- Deliberately anti-compositional: one statement per line, one binding per statement, word operators. Written by machines, reviewed by humans.

Benchmark on a CypherBench slice (60 q, same model + retry budget both sides, Cypher executed live on Neo4j): 73.3% → 98.3% overall for Haiku 4.5, 56% → 96% multi-hop. Sonnet 5 writing Cypher was no better than Haiku writing Cypher, which is the corpus-not-capacity argument in one data point.

Engine is a single-process Python WAL+snapshot store; the language spec is normative and evolves through proposal issues. I'd take criticism of the grammar (docs/language-spec) as a gift.

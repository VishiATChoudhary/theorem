# Domain forums, Discords, communities

One short honest post per venue, tuned to local norms. Space these over days 1-5. Read each venue's self-promo rules first; where a rule says "no self-promo", lead with the benchmark discussion and let the repo be a footnote.

---

## Neo4j Community Forum (community.neo4j.com, "Projects & Collaboration")

**Title:** Benchmark: where text2cypher fails structurally, and an experiment in designing around it

**Post:**

Long-time reader of the text2cypher work here. I ran a CypherBench slice with Cypher executed live on Neo4j (Haiku 4.5 and Sonnet 5, one repair retry) and got 73.3% / 71.7% EX, consistent with published numbers. Categorizing the failures: reversed relationship direction, hallucinated labels/properties, and implicit grouping dominate; they're structural, and they didn't improve with the bigger model.

As an experiment I designed a small verification-first query language around exactly those failure modes and reran the identical slice: 98.3% with the small model. Writeup, failure taxonomy, and the harness (which might be independently useful to anyone benchmarking text2cypher setups; it does live Neo4j execution against CypherBench gold) are here: github.com/VishiATChoudhary/theorem

To be clear about scope: this is not a Neo4j replacement, it's a single-process research engine. The interesting question for this community is whether any of the language-level findings (role-named traversal, staged aggregation, whole-query schema verification with did-you-mean errors) could inform how Cypher generation tooling prompts and validates. The failure taxonomy applies directly to text2cypher pipelines. Happy to share per-question results.

---

## Memgraph Discord / Kuzu Discord (#show-and-tell or equivalent)

Hey all, sharing a research project: theorem, an agent-first graph query language with its own small engine. Core idea: LLMs fail at Cypher structurally (reversed arrows, hallucinated schema, implicit grouping), so the language makes those unrepresentable, and verifies every query whole against the live schema before execution. On a CypherBench slice, that took a small model from 56% to 96% on multi-hop questions. Apache-2.0, spec-first evolution: github.com/VishiATChoudhary/theorem. Curious whether the embedded/analytical crowd here sees a role for a verification layer like this in front of existing engines.

---

## LangChain Discord / LlamaIndex Discord (#show-your-work)

Built something for the "my agent writes broken Cypher" problem. Instead of prompt-engineering around it, it's a different query language the agent targets: verified whole against the schema before execution, no direction arrows to reverse, corrective did-you-mean errors the repair loop can act on. Same small model went 73% → 98% execution accuracy on a CypherBench slice. Engine included, pip install theorem, ten-minute tutorial. Would a GraphQAChain-style integration be useful? Sketching one is on my list and I'd rather build what someone would actually use: github.com/VishiATChoudhary/theorem

---

## Latent Space Discord / AI Engineer community

The "will scaling fix it" data point in this repo might interest folks here even outside graph land: on text-to-graph-query, Sonnet 5 is no better than Haiku 4.5 (71.7% vs 73.3%), while changing the target language moves both 20+ points. Corpus familiarity, not capacity, is the binding constraint, and your production schema is never in the corpus. The fix that worked was making the language schema-closed and verification-first. Repo + technical report: github.com/VishiATChoudhary/theorem

---

## MLOps Community Slack (#tools)

Open-sourced theorem: a graph query+construction language for agent pipelines. The ops-relevant bits: every write returns a receipt (id, position, guards, dup candidates found at write time), full lineage on merges/refinements, queryable per-node health scores, and token-budgeted results with continuation handles, so agent context cost is bounded by the database, not the prompt. Benchmark + report in repo: github.com/VishiATChoudhary/theorem

---

## r/Neo4j

**Title:** Ran CypherBench live against Neo4j with Haiku + Sonnet; failure taxonomy and an experimental alternative language

Same content angle as the Neo4j forum post above, compressed, with the harness offered as the primarily useful artifact.

---

## Knowledge Graph Conference community / Ontolog forum / W3C KG community group

**Subject:** Agent-authored knowledge graphs: a verification-first construction language with provenance, lineage, and dedup receipts

For this audience lead with the WRITE surface, not the query benchmark: assert-with-provenance, write-time dedup candidates, explicit merge/distinct with permanent aliases and recorded pre-merge states, refine/compact granularity verbs with lineage, temporal retirement, derived provisional classes with quotas. Position: most agent-memory failures are curation failures, and curation needs language-level support. Mention the query benchmark in one sentence. Link repo + report.

---

## Python Discord (#showcase), r/Python

**Title:** theorem: a graph query language + engine for AI agents, pure Python stdlib, property-tested with Hypothesis

Angle for Python crowd: zero runtime dependencies, single-process WAL+snapshot engine in readable Python, 119 tests in under two seconds, Hypothesis property tests that caught two real bugs before launch (casefold-order in accent folding, torn-WAL recovery). `pip install theorem`. The parser/verifier/executor split is small enough to read in an afternoon and PRs are genuinely wanted (good-first-issue list up).

---

## Awesome-list PRs (week 1-2)

- awesome-knowledge-graph (shaoxiongji, totogo): under "Knowledge Graph Construction" or "Query Languages"
- awesome-llm-agents / awesome-ai-agents: under tools/memory
- awesome-graph (jbmusso): query languages section
- awesome-python: database section (only after PyPI downloads look respectable; this list rejects young projects)

PR description template: one line, factual: "theorem: graph query and construction language designed for LLM agents; schema-verified before execution; Apache-2.0."

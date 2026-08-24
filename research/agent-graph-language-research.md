# Deep Research: What It Takes to Build a Graph Language Optimized for Agents

Compiled 2026-08-24 from four parallel research sweeps: (1) existing graph language landscape, (2) how agents interact with graphs today, (3) what makes syntax LLM-friendly, (4) the mechanics of building a language. All claims sourced at the bottom of each section.

---

## 1. The short version

Nobody has built this yet, and the evidence says it is both needed and possible.

The plain story: when an AI agent wants to ask a graph database a question today, it has to write a query in a language made for humans (usually Cypher, the language of Neo4j). Even the best models get roughly 40% of these queries wrong on realistic schemas. The industry's reaction has been to give up on query languages entirely and hide the graph behind a handful of search buttons, which throws away the ability to ask rich, composed questions. Nobody has tried the third option: fix the language itself. That is the gap.

Three findings make the project credible:

1. **The failure modes are structural, not random.** LLMs fail at Cypher in predictable ways: they reverse edge directions, invent schema elements that do not exist, and match patterns that are valid but mean the wrong thing. A language can make each of these mistakes impossible by design.
2. **A purpose-built DSL can beat a familiar language.** The Anka result: a DSL designed for LLM generation, with zero pretraining exposure, beat Python by 40 percentage points on multi-step tasks (100% vs 60%), purely by removing error-prone degrees of freedom. Familiarity is the default advantage but it is beatable.
3. **You do not have to build a database.** Transpile to Cypher/SQL-PGQ on an embedded engine. The whole project collapses to a compiler plus a spec plus an eval harness, which is solo-feasible.

(Glossary: *Cypher* = Neo4j's graph query language, the most common one. *Schema* = the list of allowed node types, edge types, and properties in a graph. *DSL* = domain-specific language, a small language built for one job. *Transpile* = compile your language into another existing language instead of executing it yourself.)

---

## 2. Evidence: why existing languages fail agents

### Generation accuracy is bad and tracks corpus frequency, not language quality

- CypherBench (11 property graphs, 7.8M entities, 10k+ questions): Claude 3.5 Sonnet 61.6% execution accuracy, GPT-4o 60.2%, no model under 10B above 20%. Best frontier models fail \~40% with clean schemas in context. \[arXiv 2412.18702\]
- Neo4j's own Text2Cypher benchmark (44k pairs): best models \~30% on execution-based exact match. \[neo4j.com/blog/developer/benchmarking-neo4j-text2cypher-dataset\]
- SPARQL zero-shot: under 4% for most models (SM3-Text-to-Query). Accuracy across SQL/Cypher/MQL/SPARQL correlates with Stack Overflow post counts (SQL 673k posts vs SPARQL 6k). \[arXiv 2411.05521\]
- The new ISO standard GQL (2024) is currently a *worse* LLM target than Cypher purely from corpus scarcity; few-shot largely recovers it, and a fine-tuned 8B matches zero-shot frontier models, "indicating unfamiliarity, rather than model capacity, is the primary barrier." \[Text2GQL-Bench, arXiv 2602.11745\]

Implication both ways: any new language starts with zero corpus (worst case zero-shot), but the gap closes with schema-in-prompt, few-shot examples, and cheap fine-tunes. Design must assume in-context teaching, not pretraining familiarity.

### The recurring failure modes (each one a design target)

| Failure mode | Language-level fix |
| --- | --- |
| Reversed relationship direction (most-cited Cypher failure; whole repair systems exist just for this) | Direction-free or direction-explicit syntax with named roles instead of arrow glyphs |
| Schema hallucination (invented labels/properties) | Schema-closed vocabulary; queries validate against schema before execution; constrained decoding from schema-derived grammar |
| Pattern valid but diverges from question intent | Canonical forms (one way to say each thing), named intermediates |
| Aggregation logic errors | Explicit, staged aggregation instead of implicit grouping |
| Long-range bracket matching errors, deep nesting | Line-oriented, keyword-delimited, local syntax |

\[CypherBench error taxonomy, arXiv 2412.18702; arXiv 2606.04645; arXiv 2409.04181\]

### Serialization (how you print a graph back to the model) is not neutral

- Same KG, mean tokens per prompt: edge list 2,645; YAML 2,903; JSON 4,505; RDF Turtle 8,171; JSON-LD 13,503. Semantic-web formats cost 3-5x and do not buy accuracy. \[KG-LLM-Bench, arXiv 2504.07087\]
- Encoding choice alone swings graph-task accuracy by up to \~60 points; per-node "incident" encoding usually best. \[Talk like a Graph, arXiv 2310.04560\]
- Edge *ordering* matters up to 6x: accuracy on cross-referencing tasks collapses as the textual distance between relevant edges grows (Lost-in-Distance). Relevant edges should be adjacent and near the start or end of the block. \[arXiv 2410.01985\]
- In-context graph reasoning tops out around \~100 nodes; beyond that you need retrieval windows or algorithmic offload. \[arXiv 2408.13863\]

So an agent graph language needs an opinionated *result format*, not just a query syntax. The output side is as important as the input side.

### What the industry does instead (the competition)

- Agent memory systems (Zep/Graphiti, Mem0, Cognee, Anthropic's MCP memory server) all converged on the same shape: writes are unstructured episodes (the system does entity extraction, dedup, contradiction detection, temporal invalidation), reads are hybrid search. The agent never sees the graph. No production memory system asks the LLM to write Cypher against its own memory. \[arXiv 2501.13956; arXiv 2504.19413\]
- Memgraph explicitly recommends against direct Cypher generation: wrap curated queries in named tools instead. \[memgraph.com/blog/tools-vs-cypher-generation-in-graph-database\]
- Cost of the tool approach: it sacrifices expressivity (ad hoc aggregation, multi-hop composition) and every new question shape needs a new tool.
- The academic middle ground, agents traversing via curated primitives (Think-on-Graph, Graph-CoT, StructGPT), wins on explainability but compounds per-hop errors; the fix that works is plan-verify-execute: build a whole traversal plan, verify it against the actual schema/graph, then run it (GraphRunner: 10-50% better, 3-13x cheaper than per-hop agent loops). \[arXiv 2507.08945\]

---

## 3. Evidence: what makes syntax LLM-friendly

Convergent heuristics across Anka, SPEAC, BAML, TOON, grammar-prompting, and schema-adaptation studies:

- **Verbose keywords over symbols.** English words leverage the language prior; symbol-dense operators concentrate errors.
- **Canonical forms.** Exactly one way to write each operation removes decision points and makes output checkable.
- **Named intermediates over chaining.** Variable shadowing and chaining confusion were 69% of Python's failures in the Anka study. Every step binds an explicit name.
- **Locality.** Syntax errors concentrate in long-range delimiter matching; prefer line-oriented, keyword-terminated blocks over nested braces.
- **Redundancy as self-check.** Declare counts and field headers up front (TOON's `items[3]{id,name}` style); gives both model and validator a checkable invariant.
- **Reasoning space before answers** in any fixed output schema; field order measurably matters.
- **Teach by example, not grammar prose.** Models learn DSLs from worked examples far better than from grammar descriptions (MTOB follow-up). Docs = example corpus.
- **Mind the prompt tax.** A novel syntax must save more tokens than its in-context tutorial costs; below a payload-size threshold, plain JSON wins (TOON generation study, arXiv 2603.03306).
- **Token-boundary alignment.** Delimiters on natural token boundaries; whole words, newline-terminated.

Two proven routes past the zero-corpus problem:

1. **Grammar prompting**: put a compact BNF grammar plus exemplars in context; makes few-shot DSL generation competitive. \[arXiv 2305.19234\]
2. **Familiar-surface compilation** (SPEAC): let the model generate in a subset of a language it knows, compile/repair to the target; raised parse success from 3% to 84.8% on a very-low-resource formal language. \[arXiv 2406.03636\]

And syntax validity is now essentially a solved, free problem: constrained decoding (XGrammar \~100x cheaper per token; OpenAI structured outputs at 100% schema conformance) guarantees parseability, and done fairly it does not hurt reasoning (the dottxt rebuttal to "Let Me Speak Freely"). A graph language can ship a schema-conditioned grammar so agents *cannot* emit invalid labels. Design effort should therefore target semantic reliability and token economics, not parseability.

Reliability triad that recurs in every working system: schema introspection before querying, plan verification against the actual graph, execution-error feedback loops (self-correction without execution feedback does not work).

---

## 4. What building the language actually requires

### The cost structure (why scope discipline matters)

The frontend is the cost center, not the engine. Materialize's SQL layer alone (\~27k LOC) is bigger than the entire underlying dataflow engine (\~16k LOC); adding SQL to a finished engine cost an estimated 15-20 engineer-years. The lever is keeping the language small and denotationally simple: the bar to aim for is "an experienced engineer can throw together a slow but correct interpreter in a week or two." \[Against SQL, scattered-thoughts.net\]

### The sane architecture: compiler, not database

PRQL and EdgeQL prove the pattern: a new language that compiles to an existing runtime survives with a small team (PRQL has no company behind it at all). Concretely:

- **Parser**: pest/chumsky (Rust) or Lark (Python) for the reference implementation; tree-sitter grammar for editors (error-tolerant, near-zero marginal cost per editor). Days to weeks of work.
- **Semantics**: define pattern-matching semantics explicitly, it is a real design axis: homomorphism vs trail vs vertex-distinct changes both result counts and complexity class (trail semantics can go NP-hard; GQL lets users pick WALK/TRAIL/ACYCLIC per query). The "Formal Semantics of Cypher" paper (arXiv 1802.09984) is the template.
- **Execution**: transpile to Cypher or SQL/PGQ. Keep a backend abstraction layer.
- **Backend candidates** (embedded, permissive license):
  - LadybugDB, the community fork of Kuzu (Kuzu was acqui-hired by Apple Oct 2025 and archived; MIT license saved it, cautionary tale for depending on VC-backed engines)
  - DuckDB + DuckPGQ (SQL/PGQ, performance competitive with Neo4j)
  - CozoDB (Datalog surface, embedded, but essentially single-author)
  - Oxigraph if RDF ever matters (evidence says it does not, for agents)
- **Adoption floor** (the openCypher/PRQL template): reference implementation as embeddable library, published grammar, TCK-style conformance suite (Gherkin), tree-sitter grammar + small LSP, web playground, docs written as example corpus.

### The part nobody else has built: the agent-side spec

This is where the novelty lives, and it is spec + eval work more than engine work:

1. **Schema-closed grammar generation**: from a graph schema, emit a GBNF/XGrammar grammar so constrained decoding can only produce schema-valid queries. Kills hallucinated labels at decode time.
2. **Verify-before-execute**: queries are plans; validate against live schema and reject with corrective, natural-language error messages (the thing that makes self-repair loops actually work).
3. **Opinionated result serialization**: incident-style encoding, relevance-ordered edges, declared counts, hard caps with explicit truncation markers (\~100-node in-context ceiling respected by design).
4. **Token budget as a language-level concept**: queries declare result budgets; the engine paginates/summarizes instead of overflowing context.
5. **Asymmetric read/write surface** (what memory systems learned): rich compositional read language; writes as episodic assertions with system-side dedup and temporal invalidation, not raw node/edge mutation.
6. **Eval harness from day one**: CypherBench-style execution-accuracy benchmark on your language vs Cypher baseline, same questions, same graphs. This is also the paper.

---

## 5. Risks and open questions

- **The zero-corpus cold start.** Anka shows a designed DSL can win, but only on tasks with 5+ operations; on 1-2 hop lookups a new language shows no advantage over familiar baselines. The pitch must center on multi-hop, compositional queries.
- **The prompt tax.** The grammar + examples that teach the language cost context every session. Must stay small enough that a one-page tutorial suffices, or ship as a fine-tune/skill.
- **"Do agents even need graphs?"** Practitioner skepticism is real (Ask HN, Oct 2025: many argue Postgres suffices). GraphRAG-Bench (ICLR 2026) documents GraphRAG frequently losing to vanilla RAG. The language needs the use cases where structure demonstrably pays: multi-hop, aggregation, temporal reasoning.
- **Standard gravity.** GQL is now an ISO standard; the safe framing is not "Cypher replacement" but "agent interface layer that compiles to the standards."
- **Benchmark contamination cuts both ways**: models will eventually train on your language; design the eval to use held-out schemas.

## 6. Suggested next steps

1. Pick the wedge: agent memory graphs (temporal, mid-size, multi-hop questions) rather than enterprise analytics. Fits the existing LossMetricKG work.
2. Write the one-page language sketch: 8-12 verbs, canonical forms, schema-closed, line-oriented. Test it purely in-context (grammar prompting) against text2cypher on a CypherBench slice before writing any compiler.
3. If the in-context prototype beats Cypher baseline on multi-hop slices, build the transpiler (target LadybugDB or DuckPGQ) and the conformance suite.
4. Paper angle: "execution accuracy of a schema-closed agent graph language vs Cypher" is a clean, benchmarkable claim, and the eval harness doubles as the artifact.

---

## Source index (primary)

- CypherBench: arXiv 2412.18702 (ACL 2025)
- Neo4j Text2Cypher 2024: neo4j.com/blog/developer/benchmarking-neo4j-text2cypher-dataset
- Text2GQL-Bench: arXiv 2602.11745
- SM3-Text-to-Query (4 languages head-to-head): arXiv 2411.05521
- KG-LLM-Bench (serialization tokens/accuracy): arXiv 2504.07087
- Talk like a Graph: arXiv 2310.04560; GraphToken: arXiv 2402.05862
- Lost-in-Distance: arXiv 2410.01985
- GraphRunner (plan-verify-execute): arXiv 2507.08945
- Zep/Graphiti: arXiv 2501.13956; Mem0: arXiv 2504.19413
- Anka DSL (designed DSL beats Python): arXiv 2512.23214
- SPEAC (familiar-surface compilation): arXiv 2406.03636
- Grammar Prompting: arXiv 2305.19234
- XGrammar: arXiv 2411.15100; structured-output debate: arXiv 2408.02442 + blog.dottxt.ai/say-what-you-mean.html
- TOON + generation cost: github.com/toon-format/toon, arXiv 2603.03306
- Against SQL (effort economics): scattered-thoughts.net/writing/against-sql
- Formal semantics of Cypher: arXiv 1802.09984; RPQ semantics: ICDT 2026 (Dagstuhl)
- GQL standard: ISO/IEC 39075:2024; G-CORE: arXiv 1712.01550
- Kuzu shutdown / LadybugDB: theregister.com (Oct 2025), ladybugdb.com; DuckPGQ: arXiv 2505.07595
- PRQL: prql-lang.org/faq; EdgeQL: geldata.com/blog/we-can-do-better-than-sql
- openCypher TCK: opencypher.org/resources
- Anthropic tool design: anthropic.com/engineering/writing-tools-for-agents; code-execution-with-MCP: anthropic.com/engineering/advanced-tool-use
- Memgraph tools-vs-Cypher: memgraph.com/blog/tools-vs-cypher-generation-in-graph-database
- GraphRAG-Bench skepticism: arXiv 2506.05690
# Conference CFPs and talks

Check each CFP portal for exact deadlines; dates below are the usual annual pattern (verify before relying on them). One abstract per venue, tuned. The arXiv preprint should go up before the first submission so every abstract can cite it.

## Priority order

1. **NODES (Neo4j online conf)**: usually November, CFP late summer. Free, online, exactly the right audience. Submit the benchmark talk.
2. **Data Council** (Austin, spring): AI/data infra track, likes contrarian systems talks.
3. **AI Engineer Summit / World's Fair**: agents track. High leverage with the agent-builder crowd.
4. **Knowledge Graph Conference** (NYC, May): the construction/curation surface talk fits better than the benchmark talk.
5. **PyCon US / EuroPython / PyData**: the "language in pure Python" implementation talk.
6. **SPLASH/Onward! or PLDI SRC**: the research-y language-design paper. Onward! explicitly welcomes provocative early work.

## Abstract A: the benchmark talk (NODES, Data Council, AI Engineer)

**Title:** Your agent can't write Cypher, and a bigger model won't fix it

**Abstract:** Frontier LLMs get 40-50% of graph queries wrong on realistic schemas, and the number has been flat for two model generations: accuracy tracks corpus familiarity, not capacity, and your production schema is never in the corpus. This talk dissects the four structural failure modes behind the number (reversed direction glyphs, hallucinated schema, implicit grouping, long-range syntax), then shows what happens when you redesign the target language around them instead of scaling the model: on a CypherBench slice, the same small model goes from 56% to 96% execution accuracy on multi-hop queries. We cover the design rules that did the work (role-named traversal, staged aggregation, whole-program schema verification with corrective errors), the within-experiment evidence that model scaling is flat on this task, and the economics: agent fleets run on small models, and a language that makes small models reliable inverts the cost curve. Everything is open source and the benchmark harness reruns on any model in one command.

## Abstract B: the construction-surface talk (KGC, Ontolog)

**Title:** Receipts, lineage, and health: what a knowledge graph needs when the curator is an agent

**Abstract:** Agent-built knowledge graphs fail less at querying than at curation: silent duplicates, unresolvable merges, granularity mismatches, and stale facts with no accountability trail. This talk presents the write surface of theorem, an open-source graph construction language where every write returns a receipt carrying provenance, guard results, and duplicate candidates detected at write time; where merge and distinct are explicit, lineage-recorded dialogues; where refine and compact move data between granularity levels without losing origins; and where per-node health (loss, query, structure, staleness) is queryable like any property. We argue from 2026 agent-memory failures (including Mem0 retiring its graph variant) that these are language-level concerns, and show the surface working end-to-end in a live construction session.

## Abstract C: the implementation talk (PyCon, EuroPython, PyData)

**Title:** Building a query language in pure Python: parser to WAL in 1,700 lines

**Abstract:** theorem is a graph query language for AI agents whose whole engine (tokenizer, recursive-descent parser, whole-program verifier, binding-table executor, WAL+snapshot storage) is dependency-free Python readable in an afternoon. This talk walks the pipeline end to end: line-oriented grammar design that eliminates bracket-matching, verify-before-execute with did-you-mean errors from difflib, trail semantics in a binding-table executor, and crash recovery from a torn write-ahead-log line. Along the way: how Hypothesis property tests caught two real bugs (unicode casefold ordering, WAL truncation) that 110 example tests missed, and how a benchmark loop forced three language changes. Aimed at anyone who thinks languages are magic; they are 1,700 lines.

## Abstract D: the PL-research angle (Onward!, PLDI SRC)

**Title:** Anti-expressive language design: optimizing a query language for machine writers and human reviewers

**Abstract:** Query languages optimize for human expressiveness: composition, nesting, terse notation. We present evidence this optimization is inverted when the writer is a language model: on graph queries, accuracy tracks corpus familiarity rather than model capacity, and the dominant errors are structural properties of the notation itself. We describe theorem, a deliberately anti-expressive graph language (one statement per line, one binding per statement, no direction glyphs, no implicit semantics, exactly one spelling per operation) with whole-program schema verification, and report that it moves small-model execution accuracy from 56% to 96% on multi-hop CypherBench questions while making correct programs byte-canonical, enabling trivial caching and audit. We discuss anti-expressiveness as a design axis, its costs for human authors, and open questions on constrained decoding against schema-derived grammars.

## arXiv

Adapt `docs/report/graphlang-v0-report.tex` (rename to theorem throughout, add repo link) and submit to cs.DB with cs.CL cross-list. Then add the citation to README, docs site, and all future posts. Also submit to Papers with Code once up.

# Why not Cypher? Won't better models fix it?

The obvious objection to theorem is that model progress will dissolve it: wait a generation or two, and frontier models will write Cypher well enough that a new language is pointless. The objection deserves a direct answer, because the evidence, ours and the field's, runs the other way. This page condenses Section 7 of the [technical report](https://github.com/VishiATChoudhary/theorem/blob/main/docs/report/graphlang-v0-report.pdf).

## Scaling has had two years and has not delivered

Between late 2024 and mid 2026 the frontier advanced from Claude 3.5 Sonnet and GPT-4o to Claude Opus 4.8 and GPT-5.5, several major model generations. Cypher generation did not move with it. Text2GraphQuery-Bench (Feb 2026, arXiv 2602.11745) evaluates exactly these newest models: 51.2% Cypher execution accuracy for Claude Opus 4.8 and 53.3% for GPT-5.5 zero-shot, rising only to 57.6% and 55.3% few-shot. On the hardest query tier, GPT-5.5 falls to 19.1% zero-shot.

Our own control is a live second data point: on the full public CypherBench test set, the same Haiku 4.5 model scores 70.4% writing Cypher and 78.0% writing theorem, and the published frontier baselines from 2024 sit below both at 60-62%. Model scaling has been flat on this task; language design has not. Dedicated Cypher repair-and-triage systems were still being published in June 2026 (CYGNET, arXiv 2606.04645), which is not what an about-to-be-solved problem looks like.

## The reason it stays flat is structural: corpus, not capacity

Text2GraphQuery-Bench's sharpest finding: a fine-tuned 8B model matches or exceeds the newest frontier models zero-shot on graph query generation. Unfamiliarity with the language, not model capacity, is the barrier. Accuracy across query languages tracks training-corpus size, not language quality (arXiv 2411.05521), which is why GQL, the new ISO standard, benchmarks *worse* than Cypher despite being a cleaner language.

This has a consequence the objection misses: even a model that mastered every Cypher idiom on GitHub has never seen *your* schema. Production schemas are out-of-corpus by definition, and schema hallucination is a per-deployment problem no amount of pretraining removes. theorem's answer is structural rather than statistical: the vocabulary of legal classes, edges, roles, and properties is derived from the live schema and enforced at verification, so day-one correctness on an unseen schema is a property of the system, not of the corpus.

## When syntax errors fall, the surviving errors are the dangerous ones

As supervision increases, syntax errors drop sharply while error mass shifts toward semantic and logical categories: aggregation mistakes, DISTINCT misuse, schema-linking and filter errors. This is the worst possible failure profile for an autonomous agent, because a semantically wrong Cypher query is usually still *valid*: it executes, returns plausible rows or a confident empty set, and nothing downstream knows.

theorem is aimed at precisely this residue: implicit grouping is inexpressible, identity-versus-value grouping is a spelling difference, direction is a named role rather than an arrow, aggregation is staged and named, and the verifier converts an entire class of would-be silent failures into corrective errors that state `nothing was executed.` A model that never makes a syntax error still benefits from a language in which the remaining mistakes are loud.

That claim is now measured rather than asserted. Take a query known to be correct, break one token the way models break them, and ask what the caller sees. Across 3,925 such mutants on two graphs, theorem refuses 1,811 of 1,928 and text2cypher refuses **none** of 1,997: every broken Cypher query returns rows or a confident empty set, and Neo4j's own `01N42` notification fires on a call that succeeded, never on a reversed arrow, and is read by no published text2cypher pipeline. The full table, including the one case theorem does not catch, is on the [silent-failure benchmark](benchmarks/silent-failure.md) page.

The exception is worth stating plainly, because it bounds the claim. A reversed role is only catchable when an edge's two roles hold different classes. `hasFather(subj: person, obj: person)` is type-correct either way round, so swapping them asks a different question rather than an invalid one, and no schema check can tell. On a graph with five such edges, half of theorem's direction mutants survive. Naming the role rather than drawing an arrow does not make that case checkable; it makes it a wrong *word* instead of a wrong character, which is a claim about how often models make the mistake, and that is what the execution-accuracy benchmark measures.

## A perfect Cypher generator still lacks the agent surface

Suppose the objection wins completely and some future model writes flawless Cypher. What it writes flawless Cypher *against* is a database that answers "1 row affected." Nothing in Cypher, GQL, or their engines provides what agent construction workloads need: provenance-carrying writes, receipts that surface duplicate candidates at write time, an explicit merge/distinct resolution dialogue, lineage that makes merges unwindable, granularity verbs, temporal retirement, queryable health, or token-budgeted results with declared counts and continuations.

The 2026 agent-memory landscape confirms nobody else is building this surface: production systems still ingest episodically through LLM extraction pipelines, and Mem0 removed its graph variant after finding it lost on recall while running three times slower at twice the token cost. Those are write-surface and economics failures, not generation failures, and model quality does not touch them. The read side has the same economics: an identical knowledge graph costs 2,645 tokens as an edge list and 13,503 as JSON-LD (arXiv 2504.07087), and accuracy collapses with textual distance between related facts (arXiv 2410.01985). What the database prints is a property of the database.

## Even for a perfect generator, the economics invert

Our results show a small, cheap model using theorem outperforming the published frontier Cypher baselines (78.0% against 61.6% for Claude 3.5 Sonnet and 60.2% for GPT-4o), and beating the same model writing Cypher by 7.7 points. Agent fleets run on small models because they issue thousands of queries; a language that moves reliable graph access down-market is worth more than a frontier model that matches it at many times the price.

Canonical forms add a compounding benefit that *improves* as generation improves: when there is exactly one way to write each operation, two correct answers to the same question are the same program. That makes plan caching and auditing possible. The better the models get, the more of their output can be cached, verified, and trusted, but only in a language canonical enough to make equality meaningful. The one redundant spelling the language accepts, a condition qualified by its own binding, is normalized away in the parser, so equality holds of the parsed program rather than of the text.

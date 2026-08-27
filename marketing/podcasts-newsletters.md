# Podcast and newsletter pitches

Send week 2+, after the launch numbers exist ("the Show HN hit X points", "N stars in week one") so the pitch has social proof. Short pitches win; hosts skim.

## Podcasts

### Talk Python To Me (Michael Kennedy)

Subject: Pitch: a query language + engine in pure Python that makes small LLMs beat frontier models

Hi Michael, I built a graph query language for AI agents entirely in dependency-free Python: tokenizer, parser, verifier, executor, and a WAL+snapshot storage engine in about 1,700 lines. The hook for your audience: with the right target language, Claude Haiku beats frontier models writing Cypher by 25+ points, and the whole thing is readable in an afternoon and property-tested with Hypothesis (which caught two real bugs example tests missed). Recently open-sourced, picked up [traction numbers]. Happy to go deep on parser design, Hypothesis workflows, or why the engine has zero dependencies. Repo: github.com/VishiATChoudhary/theorem

### Latent Space (swyx & Alessio)

Subject: Pitch: evidence that scaling won't fix agent-database access (and what did)

The claim, with receipts: text-to-Cypher accuracy has been flat for two model generations (51-58% EX for Opus 4.8/GPT-5.5), our live runs show Sonnet 5 no better than Haiku 4.5, and a fine-tuned 8B matches frontier, so the constraint is corpus, not capacity. What moved the number 20-30 points was redesigning the query language around agent failure modes. I think this generalizes: "design the interface for the model" beats "wait for the model" across agent infrastructure. Open-source, benchmarked, technical report available. Would love to argue this on the pod.

### Practical AI (Chris Benson & Daniel Whitenack)

Angle: practical agent reliability. Small models + verified languages as the production-economics play; the write surface (receipts, dedup, lineage, health) as the unsexy operational half nobody builds.

### Data Engineering Podcast (Tobias Macey)

Angle: the storage engine and the write path. WAL + immutable snapshots in one process, receipts as the data contract with agent writers, lineage-never-pruned as a design decision, token budgets as a query-result SLA. Tobias likes systems trade-off discussions; bring the "why not just Postgres/Neo4j" answers.

### How AI Is Built (Nicolay Gerold)

Angle: knowledge-graph construction by agents end to end; the dedup pipeline (blocking + similarity + explicit resolution) and health scores in practice.

## Newsletters (submission or tip line)

### TLDR AI
One-liner: theorem, an open-source graph query language designed for LLM agents: schema-verified before execution, takes a small model from 56% to 96% on multi-hop graph queries. github.com/VishiATChoudhary/theorem

### The Sequence (Jesus Rodriguez)
Angle: the corpus-vs-capacity argument as an editorial hook; offer the benchmark table and spider chart.

### Python Weekly / PyCoder's Weekly
Submit the repo link with: "theorem: a graph query language and engine for AI agents in pure stdlib Python; Hypothesis-tested, 119 tests, pip install theorem."

### Data Elixir
Submit under tools: graph construction language with provenance, lineage, and write-time dedup for agent pipelines.

### Import AI (Jack Clark)
Research angle, keep it one paragraph: language design beats model scaling on text-to-graph-query; within-experiment scaling control (Sonnet 5 ≈ Haiku 4.5 on Cypher) plus the 20-30 point language effect; link report + harness.

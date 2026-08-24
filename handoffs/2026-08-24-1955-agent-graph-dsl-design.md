# Handoff — Agent-optimized graph DSL design (name TBD, ex-"Trellis")

**Date:** 2026-08-24 19:55  **Branch:** main  **HEAD:** fa858c2 Initial commit
**Working tree:** untracked: `.gitignore`, `archive/`, `experiments/`, `research/` (nothing committed since init)

## What's DONE

- Brainstorming session (superpowers:brainstorming, architectural path) for an agent-optimized graph DSL + engine. Settled 7 decisions via Q&A:
  1. Engine IS in scope (user explicitly chose "build scalable engine too", billions of datapoints)
  2. Workload: all three equally (agent KG construction, agent memory, analytics)
  3. Granularity: agent-explicit primitives (refine/compact verbs, agent decides, system enforces + keeps lineage)
  4. Dedup: system detects (blocking + embeddings), agent resolves (merge/distinct)
  5. Failure nodes: all four signal families (construction-loss, query-failure attribution, structural anomalies, staleness) PLUS the 5 LLM query-generation failure modes from research doc Section 2 attacked by language design
  6. Writes: full structural writes (assert/merge/refine/compact/retire), NOT episodic ingest
  7. Schema: agents evolve via `derive class`, gated (provisional status, quotas, promotion)
- Design briefing PDF written + compiled (tectonic):
  `/Users/vishi/repos/LossMetricKGConstruct/research/design-briefing/trellis-design-briefing.tex` / `.pdf`
  Contains 18 numbered decision boxes with recommendations, consolidated checklist, annotated reading list (14 sources). Decisions 1–14 gate language spec + in-context prototype; 15–18 gate engine.
- Query language explainer PDF written + compiled:
  `/Users/vishi/repos/LossMetricKGConstruct/research/design-briefing/query-language-explainer.tex` / `.pdf`
  Part I: SQL/Cypher/SPARQL/Gremlin/GQL examples on shared supply-chain running example + failure boxes. Part II: new-language features as diffs. Part III: writes/receipts/dedup/granularity/health/derive-class. Ends with end-to-end construction session transcript.
- Name research: "Trellis" was working name, "Algo" rejected (collides with ALGO 1961, ALGOL, Algoid, ALGO arXiv 2305.14591, Algorand ticker, Spanish "algo"). **Name now TBD per user.** Syntax is name-independent.

## What's LEFT — pick up here

1. **User reads both PDFs and marks decisions 1–18** (agree with recommendation or pick another option). Checklist table near end of trellis-design-briefing.pdf. This is the blocker for everything else.
2. After decisions: write design sections per brainstorming skill (present in chat, section by section, get approval each), then spec to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, then superpowers:writing-plans.
3. Agreed cheapest falsification (also in memory): in-context prototype vs text2cypher on CypherBench slice BEFORE any compiler/engine code. Grammar prompting, hand-translated gold queries, mechanical mapping to Cypher.
4. Pick a language name (user: TBD). Candidates floated: Trellis (my vote), Lattice, Arbor, Vine.

## Key files (full paths)

| Path | Role |
|------|------|
| `/Users/vishi/repos/LossMetricKGConstruct/research/agent-graph-language-research.md` | Deep-research foundation: benchmarks, failure modes, syntax evidence, engine economics, sources. Section 2 = the 5 failure modes ("failure nodes" per user) |
| `/Users/vishi/repos/LossMetricKGConstruct/research/design-briefing/trellis-design-briefing.tex` | Decision briefing LaTeX source (18 decision boxes) |
| `/Users/vishi/repos/LossMetricKGConstruct/research/design-briefing/trellis-design-briefing.pdf` | Compiled briefing for user review |
| `/Users/vishi/repos/LossMetricKGConstruct/research/design-briefing/query-language-explainer.tex` | Explainer LaTeX source (old languages vs new features, all examples) |
| `/Users/vishi/repos/LossMetricKGConstruct/research/design-briefing/query-language-explainer.pdf` | Compiled explainer (opened for user) |
| `/Users/vishi/repos/LossMetricKGConstruct/experiments/token_encoding_bench.py` | Existing token-encoding benchmark script |
| `/Users/vishi/repos/LossMetricKGConstruct/archive/v1/experiments/out/emb_nomic-embed-text.json` | Only artifact from archived v1 experiments |
| `/Users/vishi/.claude/projects/-Users-vishi-repos-LossMetricKGConstruct/memory/MEMORY.md` | Memory index for this project |
| `/Users/vishi/.claude/projects/-Users-vishi-repos-LossMetricKGConstruct/memory/lossmetric-kg-papers.md` | Two-paper plan (AgentSD + Who Verifies the Agents, PolyGraph) |
| `/Users/vishi/.claude/projects/-Users-vishi-repos-LossMetricKGConstruct/memory/agent-graph-language.md` | Prior session note: research done, next step in-context prototype vs CypherBench |
| `/Users/vishi/.claude/projects/-Users-vishi-repos-LossMetricKGConstruct/memory/paper-writing-preferences.md` | Writing prefs: flowing narrative, no AI tells, branded names |
| `/Users/vishi/.claude/projects/-Users-vishi-repos-LossMetricKGConstruct/memory/explain-plain-then-gloss-jargon.md` | User unfamiliar with KG/DB jargon; plain story first, gloss after |

## PolyGraph / "receipts" paper artifacts (user asked these be listed)

Memory (`lossmetric-kg-papers.md`, 2026-08-19) references `paper/paper.tex` (AgentSD maintenance paper, "Your Knowledge Graph Is Rotting") and `paper-verify/paper.tex` (PolyGraph, "Who Verifies the Agents?" workshop, deadline Aug 29 2026 AoE). **Those directories do NOT exist in this repo's current working tree** and searches (`find`/`mdfind`/grep over `/Users/vishi/repos`, depth-limited) found no LaTeX sources for either paper anywhere on disk. Likely a different clone, machine, or Overleaf. What DOES exist locally, compiled outputs only:

| Path | Role |
|------|------|
| `/Users/vishi/Downloads/keep-your-receipts.pdf` | Compiled "Keep Your Receipts" paper (this appears to be the receipts/verification paper, plausibly PolyGraph renamed) |
| `/Users/vishi/Downloads/keep-your-receipts-intro.pdf` | Intro excerpt of same |
| `/Users/vishi/Downloads/keep-your-receipts-supplementary.zip` | Supplementary materials |
| `/Users/vishi/Downloads/paper.pdf` | Compiled paper, likely the AgentSD maintenance paper (unverified) |

Next session: ask user where the LaTeX sources live before any paper edits. Note "receipts" also names a DSL feature (write receipts) in the explainer PDF; two different things.

## Gotchas / notes

- LaTeX compiles ONLY with `tectonic` (never pdflatex/latexmk). `tectonic -c minimal <file.tex>`.
- User instruction: NEVER use em dashes in any output including docs.
- Caveman mode active in chat (hook-enforced, terse responses); documents/code written normal.
- rtk proxy rewrites shell commands; `find` with compound predicates fails under rtk, use plain find syntax.
- Repo is one initial commit; all real content untracked. Consider committing research/ + design-briefing/ next session (user hasn't asked; ask first).
- Explainer syntax follows briefing's RECOMMENDED options for decisions 1–14; if user flips any decision, explainer examples must be updated to match.
- Both PDFs use branded working name "Trellis" in title/filenames of briefing; name officially TBD, may need rename pass.

## Open questions

- Which options for decisions 1–18 (user reading material now)
- Language name
- Where are paper/paper.tex and paper-verify/paper.tex sources? (Aug 29 deadline for PolyGraph/receipts paper is 5 days away)

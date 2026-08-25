# theorem: open-source launch design

Date: 2026-08-26
Status: draft for review

## Goal

Turn GraphLang v0 into a public community project named **theorem** (always lowercase), launched founder-voice, with three outcomes at once: contributors, adoption by agent builders, and research credibility.

Decisions already made with the user:

- Name: **theorem**, lowercase everywhere. PyPI name is free (verified 2026-08-26); GitHub has no exact-name blockbuster.
- License: **Apache-2.0** with **DCO** sign-off (no CLA). Company (Invertix) uses it freely; community owns the project together.
- Voice: personal founder voice. Repo under the personal GitHub account.
- Website: GitHub Pages docs site (no custom landing page for v0).
- Distribution: PyPI package `theorem`, published (name reservation at minimum) at launch.
- Marketing material lives on a dedicated branch off `main`.

## 1. Rename: graphlang → theorem

- Python package and module `theorem`; CLI `python -m theorem`; REPL flag unchanged.
- File extension `.thm` (was `.gl`). Grammar, spec, tutorial, eval prompts updated.
- Tagline: "theorem: a graph language agents can't get wrong. Every query verified whole before it runs."
- Repo renamed/pushed to `github.com/VishiATChoudhary/theorem`. Git history preserved.
- All docs, eval harness, viz, and tests updated to the new name. `rg -i graphlang` returns zero hits when done (except historical spec decision notes, which keep their original text with a one-line rename note).

## 2. Repo hygiene (contributor-ready)

- `LICENSE`: Apache-2.0. `NOTICE` file with copyright line.
- `CONTRIBUTING.md`: dev setup (uv), test loop, DCO sign-off instructions (`git commit -s`), PR checklist, and the language-evolution rule: syntax/semantics changes are spec-first (proposal issue, spec PR, then implementation).
- `CODE_OF_CONDUCT.md`: Contributor Covenant 2.1.
- `SECURITY.md`: private disclosure contact.
- `.github/ISSUE_TEMPLATE/`: bug report, language proposal, benchmark result.
- `.github/PULL_REQUEST_TEMPLATE.md` with DCO reminder.
- `ROADMAP.md`: v0.2 targets seeded from known gaps (union, optional-match, edge-property queries, multi-process story).
- ~10 good-first-issues drafted and filed at launch (from benchmark exclusions, TODO scan, and small ergonomics wins).

## 3. Heavy CI/CD (GitHub Actions)

- `test.yml`: pytest matrix over Python 3.11/3.12/3.13 x ubuntu/macos/windows; ruff lint + format check; coverage report with a floor gate.
- Edge-case hardening before launch: property-based tests (Hypothesis) for parser round-trips, verifier rejection completeness, storage WAL crash-recovery, budget truncation boundaries; adversarial fixture suite (unicode/accents, empty graphs, deep chains, null ordering, huge results).
- Codex review pass (codex:rescue skill) over parser, verifier, executor, storage: explicitly hunting unhandled edge cases; findings become tests first, then fixes.
- `release.yml`: tag push -> build with uv -> publish to PyPI via trusted publishing (OIDC, no long-lived token).
- `docs.yml`: MkDocs build + deploy to GitHub Pages on push to main.
- DCO check on PRs (GitHub DCO app or action).

## 4. Flashy README

Landing-page-quality README on `main`:

- Logo/wordmark (simple text-based SVG, lowercase "theorem"), tagline, badges (CI, PyPI, license, Python versions).
- Hero: the 98.3% vs 73.3% number up top, spider diagram early.
- Animated terminal GIF of a REPL session (vhs or asciinema-to-GIF).
- 60-second quickstart: `pip install theorem`, one runnable example.
- "Why not Cypher" condensed to five bullets with a link to the full argument.
- Community section: contributing link, roadmap link, good-first-issue link.

## 5. Docs site (GitHub Pages, Material for MkDocs)

Pages: landing (mirrors README hero), 10-minute tutorial, full language spec (adapted from `docs/superpowers/specs/`), benchmark page (numbers, spider chart, repro commands), "why not Cypher" essay (Section 7 of the report), contributing guide.

## 6. Packaging

- `pyproject.toml`: name `theorem`, version 0.1.0, metadata (description, urls, classifiers, keywords), console entry point `theorem`.
- Publish 0.1.0 to PyPI at launch; name reservation happens as the first implementation step so it cannot be squatted mid-work.

## 7. Marketing material (branch `launch-material` off `main`)

All drafts live in `marketing/` on the branch, one file per channel, ready to paste.

### Written pieces

- **Long-form article** (canonical piece, cross-posted Substack + Medium + dev.to): "LLMs can't write Cypher. So I built a language they can't get wrong." Failure modes -> design decisions -> benchmark -> open-source ask.
- **Twitter/X thread** (~8 tweets): hook number, example query, spider chart, repo link, contributor ask.
- **LinkedIn founder post**: why language design beats model scaling; credibility angle.
- **Reddit** (three tuned posts): r/programming (language-design angle), r/MachineLearning (benchmark/eval angle), r/LocalLLaMA (small-model angle: Haiku 4.5 at 98.3% beats frontier models writing Cypher).
- **Show HN + lobste.rs** drafts (optional to fire, but drafted).

### Domain-specific forums and communities

- Graph DB: Neo4j Community forum, Memgraph Discord, Kuzu Discord, TigerGraph community, r/Neo4j, ArangoDB community.
- Agent/LLM builders: LangChain Discord, LlamaIndex Discord, Latent Space Discord, MLOps Community Slack, AI Engineer community, r/LangChain, r/AI_Agents.
- Knowledge-graph/semantic-web: Knowledge Graph Conference community, Ontolog forum, W3C KG community group.
- Python: Python Discord showcase, r/Python, PyCoder's Weekly / Python Weekly newsletter submissions.
- Awesome-list PRs: awesome-knowledge-graph, awesome-llm-agents, awesome-graph.
- Each gets a short, honest "I built this, feedback wanted" post tuned to local norms (drafted per venue; no copy-paste spam).

### Conferences and talks (CFP targets, drafted abstract included)

- NODES (Neo4j online conference, November; CFP usually open late summer).
- Knowledge Graph Conference (NYC, May 2027).
- Data Council (Austin, spring 2027).
- AI Engineer Summit / World's Fair.
- PyCon US 2027 + regional PyData events.
- SPLASH/Onward! or PLDI SRC for the language-design research angle; arXiv preprint of the technical report to make it citable.

### Podcasts and newsletters (pitch drafts)

- Podcasts: Talk Python To Me, Latent Space, Practical AI, Data Engineering Podcast, How AI Is Built.
- Newsletters: TLDR AI, The Sequence, Data Elixir, Import AI (research angle).

## Build order

1. Rename (everything depends on the name).
2. PyPI name reservation (squat protection, minutes after rename compiles).
3. Repo hygiene files.
4. CI/CD + edge-case hardening + Codex review loop.
5. Flashy README.
6. Docs site.
7. Packaging: publish 0.1.0.
8. Marketing branch with all channel material.

Launch = flipping the repo public + firing the announcement posts; that final go is manual and user-triggered.

## Out of scope for v0 launch

Custom landing page/domain, standalone binary distribution, Rust engine, GitHub org migration, paid promotion.

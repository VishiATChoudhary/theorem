# Contributing to theorem

Thanks for wanting to make theorem better. This document covers everything you need to get a change merged.

## Development setup

theorem uses [uv](https://docs.astral.sh/uv/) and has zero runtime dependencies.

```bash
git clone https://github.com/VishiATChoudhary/theorem
cd theorem
uv sync
uv run pytest -q        # full suite, should pass in under a second
uv run python -m theorem --repl
```

## The test loop

- Every change needs tests. Bug fixes add a regression test first (watch it fail, then fix).
- `uv run pytest -q` must pass on your branch.
- Parser, verifier, and engine changes should include edge cases: empty inputs, unicode, nulls, budget boundaries.

## How language changes work (spec-first)

theorem is a language, so syntax and semantics changes carry more weight than code changes:

1. Open a **language proposal** issue describing the problem, the proposed syntax, and at least one worked example.
2. Discussion happens on the issue. Small ergonomic wins move fast; anything touching semantics needs a clear motivation (a benchmark failure, an expressiveness gap, an agent failure mode).
3. Once there is agreement, a PR updates the language spec in `docs/` first, then the implementation with tests.

Pure engine work (performance, storage, dedup quality) skips this and goes straight to a PR.

## Sign your commits (DCO)

We use the [Developer Certificate of Origin](https://developercertificate.org/). Sign off each commit:

```bash
git commit -s -m "your message"
```

This adds a `Signed-off-by:` line certifying you have the right to submit the code under the project license (Apache-2.0). No CLA, no paperwork; the sign-off is the whole process.

## Pull request checklist

- [ ] Tests pass locally (`uv run pytest -q`)
- [ ] New behavior has tests
- [ ] Commits are signed off (`git commit -s`)
- [ ] Language changes: spec updated in the same PR
- [ ] No new runtime dependencies without prior discussion

## Where to start

Look for issues labeled [`good first issue`](https://github.com/VishiATChoudhary/theorem/labels/good%20first%20issue). The [ROADMAP](ROADMAP.md) lists larger directions; comment on an issue before starting big work so nobody duplicates effort.

## Code of conduct

Everyone interacting in the project is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

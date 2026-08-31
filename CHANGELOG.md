# Changelog

Versions follow the 0.x line: the language surface in
[docs/language-spec.md](docs/language-spec.md) is what the benchmarks pin
and is the least likely thing to move; everything else may.

## 0.3.1

First version on PyPI: https://pypi.org/project/theoremql/

### Changed

- **The distribution is named `theoremql`.** PyPI prohibits the name
  `theorem`: it returns 404 on the JSON API, but the upload form rejects
  it outright, which is the prohibited-names path rather than the
  too-similar one. Nothing else moves. You still `import theorem`, still
  run `theorem`, and the repository keeps its name. Only `pip install`
  and an extras spec change, because an extras spec names the
  distribution: `pip install "theoremql[pdf]"`, never `theorem[pdf]`,
  which resolves nothing. `tests/test_distribution_name.py` fails if a
  message or a doc drifts back.
- Added `Documentation` and `Changelog` to the package metadata, so the
  PyPI sidebar points at the site and the release notes.

## 0.3.0

First release intended to be installed by someone else.

### Added

- **`Session.execute(program)`**: runs reads and writes and **raises** on
  failure. `run` returns the error as text because that is the agent
  contract, which meant Python code embedding theorem had to sniff a
  string to notice a refused program: the exact silent failure this
  language exists to prevent, reintroduced at the library boundary.
  `rows` raised already but refuses writes, so there was no raising path
  for a program that asserts anything.
- **`theorem canonical [file]`**: prints the one canonical spelling of a
  program, reading stdin when no file is given. No database needed. Two
  correct answers to the same question are byte-identical, so this
  compares queries rather than the text a model happened to emit.
- **[docs/using-theorem.md](docs/using-theorem.md)**: the embedding
  guide. Its self-contained snippets are executed by the test suite and
  assert their own results.
- **[skills/theorem](skills/theorem/SKILL.md)**: an agent skill for
  building and querying with the language. It points at the shipped
  tutorial rather than restating it, so it cannot drift from the prompt
  the published numbers were measured against.

### Changed

- **The CLI defaults to the base schema.** It used to open with the
  tutorial's supply-chain classes, so a project that derived its own
  `supplier` or `part` was told the class already existed. `--schema
  demo` opts back in; the tutorial now passes it.
- **A failed program exits non-zero.** `theorem prog.thm` printed the
  error and exited 0, so `theorem prog.thm && next-step` ran the next
  step on a refused program.
- The partial-commit count ("2 writes before this one committed") now
  rides on the exception as well as the rendered text, since a caller in
  code has no message to read.

### Fixed

- Install instructions pointed at `pip install theorem`, a name PyPI
  returns 404 for. They now point at the repository, and the PyPI badge
  is gone until there is something behind it.
- The `load --role` examples in the README and the tutorial named classes
  where the flag takes **columns**. `--role item=part` means "the column
  `part` names the node at role `item`".
- The PDF-extra error message named the same 404 install path.

### Documentation

- **The mutation study is no longer presented as a benchmark.** "theorem
  refuses 1,811 of 1,928 broken queries and Cypher refuses none of 1,997"
  is definitional: theorem verifies against the schema before executing
  and Cypher has no such step, so the split follows from the two language
  definitions rather than from running anything. The mutations were ours
  as well, chosen rather than sampled from real model errors. It is now a
  design note, out of the benchmark navigation, the README and the report
  summary tables. Its one citable result is a limit on this language:
  6.1% of deliberately broken theorem queries still return an answer, all
  of them a reversed role on an edge whose two roles hold the same class.

## 0.2.0

Not published. The state the benchmarking session in
[docs/report/](docs/report/) describes: the full public CypherBench test
set regenerated against the shipping prompt, three further benchmarks,
and eight defects fixed in shipped code (unterminated `upto any`, two
writers on one store, an unbounded write-ahead log, reads that wrote,
`or`/`keep` unreachable through a session, name reuse ignored under
`upto`, `find` ignoring subclasses, and a false claim in the spec).

## 0.1.0

Not published. The v0 language: parser, whole-program verifier, binding
tables, staged aggregation, token budgets, the structural write surface
(`assert`, `merge`, `distinct`, `refine`, `compact`, `retire`, `flag`,
`derive`), and the dedup and health pipelines.

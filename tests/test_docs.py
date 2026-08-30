"""The documentation is executable, and it covers the whole language.

Seven verbs shipped documented only inside a benchmark harness, which is
how a released language ends up with features nobody outside the repo can
find. Two rules stop that recurring: every example in the tutorial runs,
and every verb the parser accepts appears in the spec.
"""

import re
from pathlib import Path

import pytest

from theorem.parser import _Parser
from theorem.schema import Schema
from theorem.session import Session

DOCS = Path(__file__).resolve().parents[1] / "docs"


def blocks(name: str, lang: str) -> list[str]:
    text = (DOCS / name).read_text(encoding="utf-8")
    return re.findall(rf"```{lang}\n(.*?)```", text, re.DOTALL)


def test_the_tutorial_runs(tmp_path):
    """Every runnable block, in order, in one session, with no errors.

    The tutorial is a sequence: later blocks use bindings and schema that
    earlier ones created. Running them apart would not test that.
    """
    session = Session(tmp_path / "db", Schema.supply_chain())
    for block in blocks("tutorial.md", "theorem"):
        out = session.run(block)
        assert "error" not in out.lower(), f"{block}\n---\n{out}"
    session.close()


def test_the_deliberate_mistake_still_fails(tmp_path):
    """Section 5 promises a specific error. If the message changes, the
    tutorial is teaching something that no longer happens."""
    session = Session(tmp_path / "db", Schema.supply_chain())
    session.run('assert product {name: "PowerBank Pro", launch_year: 2025} as pb')
    for block in blocks("tutorial.md", "theorem-error"):
        out = session.run(block)
        assert "error" in out.lower()
        assert "nothing was executed" in out.lower()
    session.close()


def _verbs() -> set[str]:
    from theorem.parser import AGG_VERBS

    names = {m[len("parse_") :] for m in dir(_Parser) if m.startswith("parse_")} - {
        "aggregate"
    }
    return names | set(AGG_VERBS)


@pytest.mark.parametrize("verb", sorted(_verbs()))
def test_every_verb_is_in_the_spec(verb):
    spec = (DOCS / "language-spec.md").read_text(encoding="utf-8")
    grammar = re.search(r"```\n(.*?)```", spec, re.DOTALL).group(1)
    assert re.search(rf"\b{re.escape(verb)}\b", grammar), (
        f"the parser accepts `{verb}` and the spec does not mention it. "
        "A verb documented only in the source is a verb nobody can use."
    )


@pytest.mark.parametrize(
    "clause", ["upto", "or none", "via.", "return distinct", "keep"]
)
def test_the_added_clauses_are_in_the_tutorial(clause):
    """The spec is normative; the tutorial is how anyone finds a feature."""
    text = (DOCS / "tutorial.md").read_text(encoding="utf-8")
    assert clause in text


def test_the_version_is_stated_once_and_agrees():
    """Two copies of a version number drift; a test is cheaper than a
    release that reports the wrong one."""
    import tomllib

    import theorem

    pyproject = tomllib.loads(
        (DOCS.parent / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert theorem.__version__ == pyproject["project"]["version"]


def test_the_shipped_prompt_is_the_benchmarked_one():
    """The tutorial an agent is given used to live in the eval harness, so
    the published numbers described a prompt no user had. One copy now."""
    from eval.prompts import GRAPHLANG_TUTORIAL

    from theorem.prompt import TUTORIAL

    assert TUTORIAL is GRAPHLANG_TUTORIAL


def test_the_prompt_teaches_every_verb_it_can_write():
    from theorem.prompt import TUTORIAL

    for verb in ("find", "follow", "group", "keep", "compute", "return", "upto"):
        assert verb in TUTORIAL

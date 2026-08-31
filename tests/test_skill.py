"""The shipped skill has to stay true.

`skills/theorem/SKILL.md` is what an agent reads before touching this
language, so a stale command or a wrong claim there is worse than one in
the docs: nobody proofreads it, it just gets followed. These check the
things in it that can rot.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "theorem" / "SKILL.md"
TEXT = SKILL.read_text(encoding="utf-8")


def test_the_skill_has_the_frontmatter_a_skill_needs():
    assert TEXT.startswith("---\n")
    head = TEXT.split("---", 2)[1]
    assert re.search(r"^name: theorem$", head, re.MULTILINE)
    assert re.search(r"^description: ", head, re.MULTILINE)


def test_it_points_at_the_prompt_the_benchmarks_measured():
    """The skill must not restate the language in its own words.

    The published numbers belong to one exact tutorial. A skill that
    paraphrased it would drift from the text the numbers describe, and
    nothing would catch the drift.
    """
    from theorem.prompt import fingerprint

    assert "from theorem.prompt import TUTORIAL" in TEXT
    assert fingerprint() in TEXT, (
        f"the skill names a prompt fingerprint that is no longer current: "
        f"update it to {fingerprint()}"
    )


def test_the_command_it_tells_an_agent_to_run_works():
    out = subprocess.run(
        [sys.executable, "-c", "from theorem.prompt import TUTORIAL; print(TUTORIAL)"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "follow" in out and "return" in out


def test_the_schema_one_liner_works(tmp_path):
    from theorem import Schema, Session

    with Session(tmp_path / "mydb", Schema()) as db:
        out = db.run("schema")
    assert "classes:" in out and "entity" in out


@pytest.mark.parametrize(
    "claim",
    [
        "session.execute(program)",
        "session.rows(program)",
        "session.run(program)",
        "--role item=part --role source=supplier",
        "theorem canonical query.thm",
        "theorem --repl --db ./mydb",
    ],
)
def test_the_skill_names_a_real_surface(claim):
    assert claim in TEXT


def test_every_api_name_the_skill_uses_exists():
    import theorem

    for name in re.findall(r"\bfrom theorem import ([\w, ]+)", TEXT):
        for part in name.split(","):
            assert hasattr(theorem, part.strip()), part


def test_the_blind_spot_number_matches_the_docs():
    """If the audit is ever rerun, the skill must not keep the old figure."""
    docs = SKILL.parents[2] / "docs" / "benchmarks" / "silent-failure.md"
    assert "6.1%" in TEXT
    assert "6.1%" in docs.read_text(encoding="utf-8")

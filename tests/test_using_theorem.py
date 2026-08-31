"""The integration guide is executable.

`docs/using-theorem.md` is the page someone reads before putting this in
their own project, so a stale snippet there costs more than a stale one
anywhere else. Self-contained blocks are executed. Blocks that need a
model or a file of the reader's own are marked `# not runnable here:` and
have their API names checked instead, which is the part that rots.
"""

import ast
import re
from pathlib import Path

import pytest

import theorem

DOC = Path(__file__).resolve().parents[1] / "docs" / "using-theorem.md"
MARKER = "# not runnable here:"


def python_blocks() -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    return re.findall(r"```python\n(.*?)```", text, re.DOTALL)


RUNNABLE = [b for b in python_blocks() if MARKER not in b]
ILLUSTRATIVE = [b for b in python_blocks() if MARKER in b]


def test_the_page_has_blocks_of_both_kinds():
    """A regex that silently matched nothing would pass every test below."""
    assert len(RUNNABLE) >= 3
    assert len(ILLUSTRATIVE) >= 3


@pytest.mark.parametrize("block", RUNNABLE, ids=range(len(RUNNABLE)))
def test_a_self_contained_block_runs(block, tmp_path):
    """Each runs alone, against its own store, exactly as printed.

    The snippets assert their own results, so a wrong answer fails here
    rather than needing this test to restate what the page claims.
    """
    store = tmp_path / "mydb"
    exec(compile(block.replace('"./mydb"', repr(str(store))), str(DOC), "exec"), {})


@pytest.mark.parametrize("block", ILLUSTRATIVE, ids=range(len(ILLUSTRATIVE)))
def test_an_illustrative_block_parses_and_names_real_api(block):
    """It cannot run, but every name it imports from theorem must exist."""
    tree = ast.parse(block)
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "theorem"
        for alias in node.names
    ]
    assert imported, f"nothing imported from theorem in:\n{block}"
    for name in imported:
        assert hasattr(theorem, name), f"theorem has no {name!r}"


def test_the_three_apis_table_is_true(tmp_path):
    """run renders a failure, execute and rows raise on one."""
    from theorem import Schema, Session, VerifyError

    bad = "find suppler as s\nreturn s.name"
    with Session(tmp_path / "db", Schema.supply_chain()) as db:
        assert "unknown class" in db.run(bad)
        with pytest.raises(VerifyError):
            db.execute(bad)
        with pytest.raises(VerifyError):
            db.rows(bad)

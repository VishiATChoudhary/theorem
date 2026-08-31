"""`execute` is `run` for callers that are programs, not models.

`run` hands a failure back as text because that is what a model needs to
read and retry. A Python caller has `except` and does not have to
remember to look, so embedding theorem through `run` reintroduces the
exact failure the language exists to prevent: a well-formed string that
is not an answer. These tests pin the difference.
"""

import pytest

from theorem import ParseError, Schema, Session, VerifyError
from theorem.engine.writes import WriteError


@pytest.fixture
def db(tmp_path):
    with Session(tmp_path / "db", Schema.supply_chain()) as s:
        yield s


def test_execute_returns_the_same_text_when_nothing_fails(db):
    db.execute('assert supplier {name: "Acme", country: "DE"} as a')
    out = db.execute('find supplier where country = "DE" as s\nreturn s.name')
    assert "Acme" in out
    assert out == db.run('find supplier where country = "DE" as s\nreturn s.name')


def test_execute_raises_where_run_returns_a_verify_error(db):
    program = "find suppler as s\nreturn s.name"
    assert "unknown class" in db.run(program)
    with pytest.raises(VerifyError, match="unknown class"):
        db.execute(program)


def test_execute_raises_on_a_parse_error(db):
    with pytest.raises(ParseError):
        db.execute("find supplier as s\nreturn")


def test_execute_allows_writes_where_rows_refuses_them(db):
    db.execute('assert supplier {name: "Bolt Co", country: "IT"} as b')
    with pytest.raises(WriteError, match="rows\\(\\) runs reads"):
        db.rows('assert supplier {name: "No", country: "IT"} as n')


def test_a_failure_partway_through_says_how_much_stuck(db):
    """The one fact an exception has to carry that the rendered text does.

    Verification is all or nothing; execution is not. A caller's next move
    depends on knowing which of the two it hit, and a bare exception that
    omitted this would be worse than the string it replaces.
    """
    db.execute("derive class widget from entity with {sku: str} quota 2")
    program = "\n".join(
        f'assert widget {{name: "W{i}", sku: "S{i}"}} as w{i}' for i in range(4)
    )
    with pytest.raises(WriteError) as caught:
        db.execute(program)
    assert "at quota" in str(caught.value)
    assert "2 writes before this one committed" in str(caught.value)
    assert "did not run" in str(caught.value)
    # And they really are there: the failure was not a rollback.
    assert db.rows("find widget as w\nreturn w.name") == [["W0"], ["W1"]]


def test_a_verify_failure_leaves_nothing_behind(db):
    """The other half of the same contract, from the other side."""
    with pytest.raises(VerifyError):
        db.execute(
            'assert supplier {name: "One", country: "DE"} as one\nmerge one, ghost'
        )
    assert db.rows("find supplier as s\nreturn s.name") == []


def test_execute_does_not_change_what_run_reports(db):
    """The agent contract is unchanged: run still renders, never raises."""
    out = db.run("find suppler as s\nreturn s.name")
    assert out.endswith("nothing was executed.")

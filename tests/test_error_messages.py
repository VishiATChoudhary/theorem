"""An error should state the rule it enforces, not only the violation.

Two attempts to shrink the prompt failed the same way: the shorter
tutorials cost accuracy specifically at repair, where the model has an
error in front of it and one more try. Both would have worked if the
error had taught what the deleted prose taught. That makes error text
engine work, and this file is where the claim is checked.

Each case pairs a mistake a model actually makes with the words that
tell it what to write instead.
"""

import pytest

from theorem.parser import ParseError, parse
from theorem.schema import ClassDef, EdgeDef, Schema
from theorem.verifier import VerifyError, verify


def _schema():
    s = Schema()
    s.classes["player"] = ClassDef("player", {"name": "str", "height_cm": "int"})
    s.classes["team"] = ClassDef("team", {"name": "str", "inception_year": "int"})
    s.edges["playsFor"] = EdgeDef("playsFor", {"player": "player", "team": "team"})
    return s


def error_for(query: str) -> str:
    with pytest.raises((ParseError, VerifyError)) as e:
        verify(parse(query), _schema())
    return str(e.value)


def test_an_arrow_is_told_there_are_no_arrows():
    msg = error_for("find player as p\nfollow p -> team as t\nreturn t.name")
    assert "no arrows" in msg
    assert "arrival role" in msg


def test_a_clause_on_its_own_line_is_told_where_it_belongs():
    msg = error_for("find player as p\nlimit 5\nreturn p.name")
    assert "clause of `return`" in msg
    assert "limit 5" in msg


def test_a_where_after_return_names_keep():
    msg = error_for("find player as p\nreturn p.name where p.height_cm > 210")
    assert "keep" in msg


def test_an_unquoted_string_is_told_about_quotes():
    msg = error_for("find player where name = LeBron James as p\nreturn p.name")
    assert "double quotes" in msg
    assert '"LeBron James' in msg


def test_a_missing_value_is_still_a_missing_value():
    """The quoting hint must not swallow the plain case."""
    msg = error_for("find player where name = as p\nreturn p.name")
    assert "literal value" in msg


def test_a_per_group_aggregate_without_a_group_is_told_the_two_steps():
    msg = error_for(
        "find team as t\nfollow t playsFor player as p\n"
        "count distinct g.p as n\nreturn t.name, n"
    )
    assert "group by <binding> as g" in msg
    assert "two steps" in msg


def test_a_global_aggregate_is_offered_as_the_alternative():
    msg = error_for(
        "find team as t\nfollow t playsFor player as p\n"
        "count distinct g.p as n\nreturn t.name, n"
    )
    assert "count p as n" in msg


def test_keep_before_the_aggregate_is_told_the_order():
    msg = error_for("find team as t\nkeep t where n > 3\nreturn t.name")
    assert "must come first" in msg
    assert "keep t where n" in msg


def test_reusing_a_name_states_the_rule():
    msg = error_for("find player as p\nfollow p playsFor team as p\nreturn p.name")
    assert "same node" in msg


def test_the_wrong_role_lists_the_roles_and_their_classes():
    msg = error_for("find player as p\nfollow p playsFor player as q\nreturn q.name")
    assert "player" in msg and "team" in msg


def test_an_unknown_class_suggests_the_near_miss():
    msg = error_for("find playerz as p\nreturn p.name")
    assert "did you mean" in msg and "player" in msg


def test_nothing_was_executed_is_said_once_a_program_runs(tmp_path):
    """The promise the whole design rests on has to be in the text."""
    from theorem.session import Session

    session = Session(tmp_path / "db", _schema())
    out = session.run("find playerz as p\nreturn p.name")
    assert "nothing was executed" in out.lower()
    session.close()


def test_a_failure_partway_through_says_what_committed(tmp_path):
    """Verification is all or nothing; execution is not. An agent's next
    move depends on knowing which it hit."""
    from theorem import Schema, Session

    session = Session(tmp_path / "db", Schema.supply_chain())
    session.run("derive class widget from entity with {sku: str} quota 2")
    out = session.run(
        "\n".join(
            f'assert widget {{name: "W{i}", sku: "S{i}"}} as w{i}' for i in range(4)
        )
    )
    assert "at quota" in out
    assert "2 writes before this one committed" in out
    assert "did not run" in out
    session.close()


def test_a_program_that_fails_to_verify_says_nothing_ran(tmp_path):
    from theorem import Schema, Session

    session = Session(tmp_path / "db", Schema.supply_chain())
    out = session.run(
        'assert part {name: "Anode", unit_cost: 0.4} as p\nfind nosuchclass as x\nreturn x.name'
    )
    assert "nothing was executed" in out.lower()
    assert not session.store.nodes  # and the assert really did not run
    session.close()

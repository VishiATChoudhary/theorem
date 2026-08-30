"""`keep <binding> where <cond>`: filter rows, including after grouping.

"Which parts appear in more than three products" is the shape of every
systemic-risk question over a technical graph, and it was impossible:
`find ... where` filters before counting, and nothing filtered after.
"""

import pytest

from theorem.engine.executor import execute_rows
from theorem.parser import ParseError, parse
from theorem.schema import Schema
from theorem.verifier import VerifyError, verify

S = Schema.supply_chain()


def run(text, store, schema=S):
    return execute_rows(verify(parse(text), schema), store, schema)


# ---- the case that was impossible: filter on an aggregate ------------


def test_keep_filters_groups_by_their_count(fixture_store):
    """Parts used by more than one product. cell is in PowerBank and
    GridPack; wire, film and casing are each in one."""
    rows = run(
        "find part as p\n"
        "follow p uses whole as prod\n"
        "group by p as g\n"
        "count distinct g.prod as n\n"
        "keep g where n > 1\n"
        "return p.name, n",
        fixture_store,
    )
    assert rows == [["lithium cell", 2]]


def test_keep_with_no_survivors_is_empty(fixture_store):
    rows = run(
        "find part as p\n"
        "follow p uses whole as prod\n"
        "group by p as g\n"
        "count distinct g.prod as n\n"
        "keep g where n > 99\n"
        "return p.name, n",
        fixture_store,
    )
    assert rows == []


def test_keep_can_use_any_comparison(fixture_store):
    rows = run(
        "find part as p\n"
        "follow p uses whole as prod\n"
        "group by p as g\n"
        "count distinct g.prod as n\n"
        "keep g where n = 1\n"
        "return p.name order by p.name",
        fixture_store,
    )
    assert rows == [["casing"], ["copper wire"], ["solar film"]]


def test_keep_composes_with_order_and_limit(fixture_store):
    rows = run(
        "find part as p\n"
        "follow p uses whole as prod\n"
        "group by p as g\n"
        "count distinct g.prod as n\n"
        "keep g where n >= 1\n"
        "return p.name, n order by n desc limit 1",
        fixture_store,
    )
    assert rows == [["lithium cell", 2]]


# ---- it also filters plain rows --------------------------------------


def test_keep_before_any_aggregate(fixture_store):
    rows = run(
        "find product as p\nkeep p where launch_year > 2024\nreturn p.name",
        fixture_store,
    )
    assert sorted(rows) == [["GridPack"], ["PowerBank Pro"]]


def test_keep_on_a_followed_binding(fixture_store):
    rows = run(
        "find product as p\n"
        "follow p uses component as c\n"
        "keep c where unit_cost > 2\n"
        "return distinct c.name order by c.name",
        fixture_store,
    )
    assert rows == [["lithium cell"], ["solar film"]]


# ---- errors -----------------------------------------------------------


def test_keep_needs_a_bound_name(fixture_store):
    with pytest.raises(VerifyError):
        verify(parse("find product as p\nkeep bogus where x = 1\nreturn p.name"), S)


def test_keep_rejects_an_unknown_property(fixture_store):
    with pytest.raises(VerifyError):
        verify(parse("find product as p\nkeep p where nonsense = 1\nreturn p.name"), S)


def test_keep_needs_a_condition():
    with pytest.raises(ParseError):
        parse("find product as p\nkeep p\nreturn p.name")

"""Query shapes people (and models) write naturally.

Each of these was rejected by the language while expressing something
theorem could already compute. They are grouped by the failure they came
from in the CypherBench run.
"""

import pytest

from theorem.engine.executor import execute_rows
from theorem.parser import parse
from theorem.schema import Schema
from theorem.verifier import verify

S = Schema.supply_chain()


def run(text, store, schema=S):
    return execute_rows(verify(parse(text), schema), store, schema)


# ---- `where` may follow `as` as well as precede it -------------------


def test_find_where_after_as(fixture_store):
    before = run(
        'find product where launch_year > 2024 as p\nreturn p.name', fixture_store
    )
    after = run(
        'find product as p where launch_year > 2024\nreturn p.name', fixture_store
    )
    assert sorted(before) == sorted(after)
    assert sorted(before) == [["GridPack"], ["PowerBank Pro"]]


def test_follow_where_after_as(fixture_store):
    before = run(
        'find product as p\n'
        'follow p uses component where name = "lithium cell" as c\n'
        "return p.name",
        fixture_store,
    )
    after = run(
        'find product as p\n'
        'follow p uses component as c where name = "lithium cell"\n'
        "return p.name",
        fixture_store,
    )
    assert sorted(before) == sorted(after)


# ---- return is set-valued --------------------------------------------


def test_return_deduplicates_on_projected_bindings(fixture_store):
    """cell is reached from two products, so the raw table has it twice;
    asking for the part names must not repeat it."""
    rows = run(
        "find product as p\nfollow p uses component as c\nreturn c.name",
        fixture_store,
    )
    assert sorted(rows) == [["casing"], ["copper wire"], ["lithium cell"], ["solar film"]]


def test_return_keeps_distinct_entities_that_share_a_name(fixture_store):
    """Two different suppliers are both called Ionix. Deduplication is on
    node identity, so both must still appear."""
    rows = run(
        "find supplier as s\nreturn s.name",
        fixture_store,
    )
    assert sorted(rows) == [["Ionix"], ["Ionix"], ["VoltaChem"]]


def test_return_dedup_happens_before_limit(fixture_store):
    rows = run(
        "find product as p\nfollow p uses component as c\n"
        "return c.name order by c.unit_cost desc limit 2",
        fixture_store,
    )
    assert rows == [["solar film"], ["lithium cell"]]


def test_aggregates_still_see_every_row(fixture_store):
    """Deduplication applies to `return`, not to counting."""
    rows = run(
        "find product as p\nfollow p uses component as c\ncount c as n\nreturn n",
        fixture_store,
    )
    assert rows == [[5]]


# ---- reusing a name means "the same node" ----------------------------


def test_reused_name_joins(fixture_store):
    """Products that use a part supplied by VoltaChem, where the part
    reached both ways is the same part."""
    rows = run(
        'find supplier where name = "VoltaChem" as v\n'
        "follow v supplied_by item as part\n"
        'find product where name = "PowerBank Pro" as pb\n'
        "follow pb uses component as part\n"
        "return part.name",
        fixture_store,
    )
    assert rows == [["lithium cell"]]


def test_reused_name_with_no_overlap_is_empty(fixture_store):
    rows = run(
        'find supplier where name = "VoltaChem" as v\n'
        "follow v supplied_by item as part\n"
        'find product where name = "GridPack" as gp\n'
        "follow gp uses component where name = \"casing\" as part\n"
        "return part.name",
        fixture_store,
    )
    assert rows == []


# ---- `or` starts an alternative branch, branches are unioned ---------


def test_or_unions_two_branches(fixture_store):
    rows = run(
        'find product where name = "SolarCharger X" as p\n'
        "follow p uses component as c\n"
        "or\n"
        'find product where name = "GridPack" as p\n'
        "follow p uses component as c\n"
        "return c.name",
        fixture_store,
    )
    assert sorted(rows) == [["casing"], ["lithium cell"], ["solar film"]]


def test_or_then_aggregate_covers_the_union(fixture_store):
    rows = run(
        'find product where name = "SolarCharger X" as p\n'
        "follow p uses component as c\n"
        "or\n"
        'find product where name = "GridPack" as p\n'
        "follow p uses component as c\n"
        "count distinct c as n\n"
        "return n",
        fixture_store,
    )
    assert rows == [[3]]


def test_or_branches_may_use_different_edges(fixture_store):
    rows = run(
        'find part where name = "lithium cell" as start\n'
        "follow start supplied_by source as s\n"
        "or\n"
        'find part where name = "casing" as start\n'
        "follow start supplied_by source as s\n"
        "count distinct s as n\n"
        "return n",
        fixture_store,
    )
    assert rows == [[3]]  # VoltaChem, Ionix/KR, Ionix/JP


def test_trailing_or_is_an_error():
    with pytest.raises(Exception):
        parse("find product as p\nor\n")

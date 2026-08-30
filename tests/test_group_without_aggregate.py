"""A group is usable before anything is aggregated over it.

The tutorial says `<g>.key` is the group key, but groups were only
materialized as a side effect of the first aggregate. Grouping and then
asking for the keys, which is how you ask for distinct values, failed
with "cannot resolve column g.key".
"""

from theorem.engine.executor import ReadContext, execute_read, execute_rows
from theorem.parser import parse
from theorem.schema import Schema
from theorem.verifier import verify

S = Schema.supply_chain()


def run(text, store, schema=S):
    return execute_rows(verify(parse(text), schema), store, schema)


def test_group_key_without_an_aggregate(fixture_store):
    rows = run(
        "find supplier as s\ngroup by s.country as g\nreturn g.key order by g.key",
        fixture_store,
    )
    assert rows == [["DE"], ["JP"], ["KR"]]


def test_group_key_is_one_row_per_distinct_value(fixture_store):
    """Two suppliers are in KR only if the fixture says so; either way the
    key appears once per distinct value, not once per member."""
    rows = run(
        "find part as p\ngroup by p.unit_cost as g\nreturn g.key",
        fixture_store,
    )
    assert len(rows) == len({r[0] for r in rows})


def test_grouped_member_column_without_an_aggregate(fixture_store):
    rows = run(
        "find product as p\nfollow p uses component as c\n"
        "group by p as g\nreturn g.c.name",
        fixture_store,
    )
    assert sorted(r[0] for r in rows) == [
        "casing",
        "copper wire",
        "lithium cell",
        "solar film",
    ]


def test_group_then_aggregate_still_works(fixture_store):
    rows = run(
        "find product as p\nfollow p uses component as c\n"
        "group by p as g\ncount distinct g.c as n\n"
        "return p.name, n order by p.name",
        fixture_store,
    )
    assert rows == [["GridPack", 2], ["PowerBank Pro", 2], ["SolarCharger X", 1]]


def test_group_key_renders(fixture_store):
    out = execute_read(
        verify(
            parse("find supplier as s\ngroup by s.country as g\nreturn g.key"), S
        ),
        fixture_store,
        S,
        ReadContext(),
    )
    assert "DE" in out and "results: 3 of 3" in out

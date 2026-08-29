"""Distinct aggregation: semantics and scaling.

`count distinct` is the hot path for grouped counting queries. The dedup
must preserve first-seen order, treat equal-but-not-identical values as
one, tolerate unhashable values, and run in linear time so it stays
usable on graphs with hundreds of thousands of nodes.
"""

import time

import pytest

from theorem.engine.executor import execute_rows
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.schema import ClassDef, Schema
from theorem.verifier import verify

S = Schema.supply_chain()


def run(text, store, schema=S):
    return execute_rows(verify(parse(text), schema), store, schema)


def test_global_count_distinct_collapses_duplicates(fixture_store):
    # cell is reached from both PowerBank Pro and GridPack, so the raw
    # binding column holds it twice; distinct must count it once.
    rows = run(
        'find product where launch_year > 2024 as p\n'
        "follow p uses component as parts\n"
        "count distinct parts as n\n"
        "return n",
        fixture_store,
    )
    assert rows == [[3]]  # cell, wire, casing


def test_grouped_count_distinct(fixture_store):
    rows = run(
        'find product where launch_year > 2024 as p\n'
        "follow p uses component as parts\n"
        "follow parts supplied_by source as sups\n"
        "group by sups as g\n"
        "count distinct g.parts as n\n"
        "return sups.name, n order by n desc",
        fixture_store,
    )
    assert rows[0] == ["Ionix", 2]  # Ionix/KR supplies cell + wire


def test_count_distinct_without_distinct_keeps_duplicates(fixture_store):
    plain = run(
        'find product where launch_year > 2024 as p\n'
        "follow p uses component as parts\n"
        "count parts as n\n"
        "return n",
        fixture_store,
    )
    assert plain == [[4]]  # cell, wire, cell, casing


def _many_store(tmp_path, n):
    """A store with n suppliers, each supplying one distinct part, so a
    global `count distinct` has to dedup n values."""
    schema = Schema()
    schema.classes["widget"] = ClassDef(name="widget", props={"name": "str"})
    store = Store(tmp_path / "db")
    records = []
    for i in range(n):
        nid = store.next_id("widget")
        records.append(
            {"op": "put_node", "id": nid, "cls": "widget", "props": {"name": f"w{i}"}}
        )
    store.bulk(records)
    return store, schema


def test_count_distinct_is_linear(tmp_path):
    """Quadratic dedup made large graphs unqueryable.

    An absolute bound rather than a ratio between two sizes: ratios are
    noisy when the machine is busy, while the gap here is enormous.
    Deduplicating 20k rows is a few milliseconds linearly and takes
    2 * 10^8 comparisons quadratically, so seconds. One second separates
    them by two orders of magnitude either way.
    """
    big, schema = _many_store(tmp_path / "big", 20_000)
    q = "find widget as w\ncount distinct w as n\nreturn n"

    t0 = time.perf_counter()
    assert run(q, big, schema) == [[20_000]]
    assert time.perf_counter() - t0 < 1.0


def test_dedup_handles_unhashable_values(fixture_store):
    from theorem.engine.executor import _dedup

    assert _dedup([[1], [1], [2]]) == [[1], [2]]
    assert _dedup([1, 1.0, True, 2]) == [1, 2]
    assert _dedup(["b", "a", "b"]) == ["b", "a"]
    assert _dedup([[1], 1, [1]]) == [[1], 1]

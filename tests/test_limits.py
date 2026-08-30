"""A query has a ceiling, and the engine is where it lives.

`budget` caps how much of an answer is printed, which does nothing for a
traversal that exhausts memory before it ever reaches `return`. The
benchmark harness wrapped every query in `signal.alarm` for exactly this
reason: a limit the callers each have to remember is not a limit.
"""

import pytest

from theorem.engine.executor import ExecError, execute_rows, limits
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.schema import ClassDef, EdgeDef, Schema
from theorem.verifier import verify


def _schema():
    s = Schema()
    s.classes["item"] = ClassDef(name="item", props={"name": "str"})
    s.edges["links"] = EdgeDef(name="links", roles={"from_": "item", "to": "item"})
    return s


@pytest.fixture
def wide(tmp_path):
    """80 nodes, every node linked to every other: one follow is 6,320
    rows and two are half a million."""
    schema = _schema()
    store = Store(tmp_path / "db")
    n = 80
    ids = []
    for i in range(n):
        nid = store.next_id("item")
        store.apply(
            {"op": "put_node", "id": nid, "cls": "item", "props": {"name": f"n{i}"}}
        )
        ids.append(nid)
    records = []
    for a in ids:
        for b in ids:
            if a != b:
                records.append(
                    {
                        "op": "put_edge",
                        "id": store.next_id("edge"),
                        "type": "links",
                        "roles": {"from_": a, "to": b},
                    }
                )
    store.bulk(records)
    yield store, schema
    store.close()


def run(text, fixture):
    store, schema = fixture
    return execute_rows(verify(parse(text), schema), store, schema)


def test_a_wide_traversal_stops_instead_of_exhausting_memory(wide):
    with limits(max_rows=10_000):
        with pytest.raises(ExecError) as e:
            run(
                "find item as a\n"
                "follow a links to as b\n"
                "follow b links to as c\n"
                "return c.name",
                wide,
            )
    assert "10000" in str(e.value)


def test_the_ceiling_says_how_to_get_under_it(wide):
    """An agent reads this message and writes the next query from it."""
    with limits(max_rows=10_000):
        with pytest.raises(ExecError) as e:
            run(
                "find item as a\nfollow a links to as b\nfollow b links to as c\n"
                "return c.name",
                wide,
            )
    msg = str(e.value)
    assert "where" in msg and "limit" in msg


def test_a_query_under_the_ceiling_is_untouched(wide):
    with limits(max_rows=10_000):
        rows = run(
            'find item where name = "n0" as a\nfollow a links to as b\nreturn b.name',
            wide,
        )
    assert len(rows) == 79


def test_the_deadline_is_enforced(wide):
    with limits(seconds=0.0):
        with pytest.raises(ExecError) as e:
            run("find item as a\nfollow a links to as b\nreturn b.name", wide)
    assert "too long" in str(e.value)


def test_transitive_reach_is_bounded_too(wide):
    """`upto any` is the statement most able to run away."""
    with limits(max_rows=100):
        with pytest.raises(ExecError):
            run(
                "find item as a\nfollow a links to upto any as b\nreturn b.name",
                wide,
            )


def test_defaults_do_not_break_ordinary_queries(wide):
    rows = run(
        'find item where name = "n0" as a\nfollow a links to as b\nreturn b.name',
        wide,
    )
    assert len(rows) == 79


def test_limits_do_not_leak_out_of_the_block(wide):
    with limits(max_rows=1):
        pass
    rows = run(
        'find item where name = "n0" as a\nfollow a links to as b\nreturn b.name',
        wide,
    )
    assert len(rows) == 79


# ---- a read must not be a write ---------------------------------------


def test_a_read_writes_nothing_to_the_wal(wide):
    """Traffic telemetry used to append a WAL record per node per follow,
    which made every question a write: a read-only workload grew the log
    forever, and answering one needed write access."""
    store, _ = wide
    before = store.wal_len()
    position = store.position
    rows = run("find item as a\nfollow a links to as b\nreturn b.name", wide)
    assert rows
    assert store.wal_len() == before
    assert store.position == position


def test_the_counts_are_still_kept(wide):
    store, _ = wide
    run('find item where name = "n0" as a\nfollow a links to as b\nreturn b.name', wide)
    walked = [n for n in store.nodes.values() if n.traffic]
    assert walked, "a follow should record that it walked through nodes"

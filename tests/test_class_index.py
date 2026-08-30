"""Seeding a query should cost the class, not the whole graph.

`find <class>` scanned every node in the store and filtered by class, so
the cost of finding one of 217 countries was paid against all 885k nodes
in the graph. On the large CypherBench graphs that dominated query time.
"""

import time

from theorem.engine.executor import execute_rows
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.schema import ClassDef, Schema
from theorem.verifier import verify


def _store(tmp_path, n_big, n_small):
    schema = Schema()
    schema.classes["big"] = ClassDef(name="big", props={"name": "str"})
    schema.classes["small"] = ClassDef(name="small", props={"name": "str"})
    store = Store(tmp_path / "db")
    records = []
    for cls, n in (("big", n_big), ("small", n_small)):
        for i in range(n):
            nid = store.next_id(cls)
            records.append(
                {
                    "op": "put_node",
                    "id": nid,
                    "cls": cls,
                    "props": {"name": f"{cls}{i}"},
                }
            )
    store.bulk(records)
    return store, schema


def test_find_returns_only_that_class(tmp_path):
    store, schema = _store(tmp_path, 500, 3)
    rows = execute_rows(
        verify(parse("find small as s\nreturn s.name"), schema), store, schema
    )
    assert sorted(r[0] for r in rows) == ["small0", "small1", "small2"]


def test_find_cost_tracks_the_class_not_the_store(tmp_path):
    """Finding 3 nodes must not get 40x slower because 120k unrelated
    nodes of another class exist."""
    small_store, schema = _store(tmp_path / "a", 3_000, 3)
    big_store, _ = _store(tmp_path / "b", 120_000, 3)
    q = "find small as s\nreturn s.name"

    def timed(store):
        plans = verify(parse(q), schema)
        t0 = time.perf_counter()
        for _ in range(5):
            execute_rows(plans, store, schema)
        return time.perf_counter() - t0

    t_small = timed(small_store)
    t_big = timed(big_store)
    assert t_big < max(t_small, 0.001) * 5


def test_retired_nodes_stay_out_of_find(tmp_path):
    store, schema = _store(tmp_path, 2, 2)
    victim = [n.id for n in store.nodes.values() if n.cls == "small"][0]
    store.apply({"op": "retire", "id": victim, "reason": "gone"})
    rows = execute_rows(
        verify(parse("find small as s\nreturn s.name"), schema), store, schema
    )
    assert len(rows) == 1


def test_index_survives_replay(tmp_path):
    store, schema = _store(tmp_path, 5, 4)
    store.snapshot()
    store.close()
    reopened = Store(tmp_path / "db")
    rows = execute_rows(
        verify(parse("find small as s\nreturn s.name"), schema), reopened, schema
    )
    assert len(rows) == 4

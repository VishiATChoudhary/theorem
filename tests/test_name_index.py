"""Looking a node up by name should not read the whole class.

`find <class> where name = "..."` is the most common way a query starts,
and it scanned every node of the class. On the politics graph that meant
reading all 541k politicians to return one.

The index is a prefilter only: the condition is still evaluated on every
candidate, so matching stays case- and accent-insensitive exactly as
before.
"""

import time

from theorem.engine.executor import execute_rows
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.schema import ClassDef, Schema
from theorem.verifier import verify


def _store(tmp_path, n, extra=()):
    schema = Schema()
    schema.classes["person"] = ClassDef(
        name="person", props={"name": "str", "age": "int"}
    )
    store = Store(tmp_path / "db")
    records = []
    for i in range(n):
        nid = store.next_id("person")
        records.append(
            {
                "op": "put_node",
                "id": nid,
                "cls": "person",
                "props": {"name": f"person{i}", "age": i},
            }
        )
    for name, age in extra:
        nid = store.next_id("person")
        records.append(
            {
                "op": "put_node",
                "id": nid,
                "cls": "person",
                "props": {"name": name, "age": age},
            }
        )
    store.bulk(records)
    return store, schema


def run(text, store, schema):
    return execute_rows(verify(parse(text), schema), store, schema)


def test_lookup_by_name(tmp_path):
    store, schema = _store(tmp_path, 50, extra=[("Angela Merkel", 70)])
    rows = run(
        'find person where name = "Angela Merkel" as p\nreturn p.age', store, schema
    )
    assert rows == [[70]]


def test_lookup_is_accent_and_case_insensitive(tmp_path):
    store, schema = _store(tmp_path, 10, extra=[("Nikola Mirotić", 33)])
    assert run(
        'find person where name = "nikola mirotic" as p\nreturn p.age', store, schema
    ) == [[33]]
    assert run(
        'find person where name = "NIKOLA MIROTIĆ" as p\nreturn p.age', store, schema
    ) == [[33]]


def test_all_nodes_sharing_a_name_are_found(tmp_path):
    store, schema = _store(tmp_path, 5, extra=[("Ionix", 1), ("Ionix", 2)])
    rows = run(
        'find person where name = "Ionix" as p\nreturn p.age order by p.age',
        store,
        schema,
    )
    assert rows == [[1], [2]]


def test_other_conditions_still_work(tmp_path):
    store, schema = _store(tmp_path, 20)
    rows = run(
        "find person where age > 17 as p\nreturn p.age order by p.age", store, schema
    )
    assert rows == [[18], [19]]


def test_name_and_another_condition(tmp_path):
    store, schema = _store(tmp_path, 5, extra=[("Ionix", 1), ("Ionix", 9)])
    rows = run(
        'find person where name = "Ionix" and age > 5 as p\nreturn p.age', store, schema
    )
    assert rows == [[9]]


def test_name_lookup_does_not_scale_with_the_class(tmp_path):
    small, schema = _store(tmp_path / "a", 2_000, extra=[("Target", 1)])
    big, _ = _store(tmp_path / "b", 100_000, extra=[("Target", 1)])
    q = 'find person where name = "Target" as p\nreturn p.age'

    def timed(store):
        plans = verify(parse(q), schema)
        t0 = time.perf_counter()
        for _ in range(5):
            execute_rows(plans, store, schema)
        return time.perf_counter() - t0

    assert timed(big) < max(timed(small), 0.001) * 5

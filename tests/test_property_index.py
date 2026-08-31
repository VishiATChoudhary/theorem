"""An index may only make a query faster, never different.

`name` has always had one. Any other property was a scan: on a 275k-node
class, 288 ms against 0.03 ms for a name lookup. Indexing the rest is
worth doing and is the most dangerous kind of change this codebase can
take, because a stale index returns a plausible wrong answer, which is
the one failure the language exists to prevent.

So every test here is differential: the same query, with the index and
without it, must give the same rows.
"""

import random

import pytest

from theorem.engine.executor import execute_rows
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.schema import ClassDef, Schema
from theorem.verifier import verify

COUNTRIES = ["DE", "JP", "KR", "US", "Côte d'Ivoire", "CN"]
TIERS = [1, 2, 3]


def _schema():
    s = Schema()
    s.classes["supplier"] = ClassDef(
        "supplier", {"name": "str", "country": "str", "tier": "int"}
    )
    return s


def _store(tmp_path, n, seed=0):
    rng = random.Random(seed)
    schema = _schema()
    store = Store(tmp_path / "db")
    records = []
    for i in range(n):
        records.append(
            {
                "op": "put_node",
                "id": f"#s-{i + 1}",
                "cls": "supplier",
                "props": {
                    "name": f"S{i}",
                    "country": rng.choice(COUNTRIES),
                    "tier": rng.choice(TIERS),
                },
            }
        )
    store.bulk(records)
    return store, schema, rng


def both_ways(query, store, schema):
    """The query with whatever index exists, and with none at all."""
    plans = verify(parse(query), schema)
    indexed = execute_rows(plans, store, schema)
    saved_props, saved_index = store.indexed_props, store.by_prop
    store.indexed_props, store.by_prop = set(), {}
    store.auto_index = False  # clearing is not enough: it would rebuild
    try:
        scanned = execute_rows(plans, store, schema)
    finally:
        store.indexed_props, store.by_prop = saved_props, saved_index
        store.auto_index = True
    return sorted(map(str, indexed)), sorted(map(str, scanned))


QUERIES = [
    'find supplier where country = "DE" as s\nreturn s.name',
    'find supplier where country = "Côte d\'Ivoire" as s\nreturn s.name',
    'find supplier where country = "de" as s\nreturn s.name',
    'find supplier where country = "Cote d\'Ivoire" as s\nreturn s.name',
    "find supplier where tier = 2 as s\nreturn s.name",
    'find supplier where country = "DE" or country = "JP" as s\nreturn s.name',
    'find supplier where country = "DE" and tier = 1 as s\nreturn s.name',
    'find supplier where country = "nowhere" as s\nreturn s.name',
    'find supplier where country != "DE" as s\nreturn s.name',
    "find supplier where tier > 1 as s\nreturn s.name",
    'find supplier where name = "S3" as s\nreturn s.name',
    "find supplier as s\nreturn s.name order by s.name limit 3",
]


@pytest.mark.parametrize("query", QUERIES)
def test_the_index_never_changes_the_answer(tmp_path, query):
    store, schema, _ = _store(tmp_path, 6000)
    indexed, scanned = both_ways(query, store, schema)
    assert indexed == scanned
    store.close()


def test_a_patched_property_leaves_the_index_correct(tmp_path):
    """The failure mode: an entry under the old value that never goes away."""
    store, schema, rng = _store(tmp_path, 6000)
    both_ways('find supplier where country = "DE" as s\nreturn s.name', store, schema)
    assert store.indexed_props  # the index exists now

    for i in rng.sample(range(1, 6001), 400):
        store.apply(
            {
                "op": "patch_node",
                "id": f"#s-{i}",
                "props": {"country": rng.choice(COUNTRIES), "tier": rng.choice(TIERS)},
            }
        )
    for query in QUERIES:
        indexed, scanned = both_ways(query, store, schema)
        assert indexed == scanned, query
    store.close()


def test_nodes_added_after_the_index_are_in_it(tmp_path):
    store, schema, _ = _store(tmp_path, 6000)
    both_ways('find supplier where country = "DE" as s\nreturn s.name', store, schema)
    store.apply(
        {
            "op": "put_node",
            "id": "#s-99999",
            "cls": "supplier",
            "props": {"name": "Latecomer", "country": "DE", "tier": 1},
        }
    )
    indexed, scanned = both_ways(
        'find supplier where country = "DE" as s\nreturn s.name', store, schema
    )
    assert indexed == scanned
    assert "Latecomer" in " ".join(indexed)
    store.close()


def test_a_retired_node_stays_out(tmp_path):
    store, schema, _ = _store(tmp_path, 6000)
    q = 'find supplier where country = "DE" as s\nreturn s.name'
    both_ways(q, store, schema)
    victim = next(n.id for n in store.nodes.values() if n.props.get("country") == "DE")
    store.apply({"op": "retire", "id": victim, "reason": "gone"})
    indexed, scanned = both_ways(q, store, schema)
    assert indexed == scanned
    store.close()


def test_a_multi_valued_property_is_found_under_each_value(tmp_path):
    schema = _schema()
    store = Store(tmp_path / "db")
    store.bulk(
        [
            {
                "op": "put_node",
                "id": f"#s-{i}",
                "cls": "supplier",
                "props": {"name": f"S{i}", "country": ["DE", "JP"], "tier": 1},
            }
            for i in range(1, 6001)
        ]
    )
    for country in ("DE", "JP", "KR"):
        q = f'find supplier where country = "{country}" as s\nreturn s.name limit 5'
        indexed, scanned = both_ways(q, store, schema)
        assert indexed == scanned, country
    store.close()


def test_a_small_class_is_not_indexed_at_all(tmp_path):
    """Indexing a class a scan crosses instantly is memory for nothing."""
    store, schema, _ = _store(tmp_path, 50)
    both_ways('find supplier where country = "DE" as s\nreturn s.name', store, schema)
    assert store.indexed_props == set()
    store.close()


def test_the_index_survives_a_reopen(tmp_path):
    store, schema, _ = _store(tmp_path, 6000)
    q = 'find supplier where country = "JP" as s\nreturn s.name'
    before, _ = both_ways(q, store, schema)
    store.snapshot()
    store.close()

    reopened = Store(tmp_path / "db")
    after, scanned = both_ways(q, reopened, schema)
    assert after == scanned == before
    reopened.close()

from theorem.engine.storage import Store


def put_supplier(store, name, country="DE"):
    nid = store.next_id("supplier")
    store.apply(
        {
            "op": "put_node",
            "id": nid,
            "cls": "supplier",
            "props": {"name": name, "country": country},
        }
    )
    return nid


def test_apply_and_read(tmp_path):
    store = Store(tmp_path)
    nid = put_supplier(store, "VoltaChem")
    assert store.nodes[nid].props["name"] == "VoltaChem"
    assert store.nodes[nid].cls == "supplier"
    assert store.nodes[nid].state == "atom"


def test_positions_monotonic(tmp_path):
    store = Store(tmp_path)
    p1 = store.apply(
        {
            "op": "put_node",
            "id": store.next_id("part"),
            "cls": "part",
            "props": {"name": "a"},
        }
    )
    p2 = store.apply(
        {
            "op": "put_node",
            "id": store.next_id("part"),
            "cls": "part",
            "props": {"name": "b"},
        }
    )
    assert p2 == p1 + 1


def test_edge_incident_both_ends(tmp_path):
    store = Store(tmp_path)
    a = put_supplier(store, "VoltaChem")
    b = store.next_id("part")
    store.apply({"op": "put_node", "id": b, "cls": "part", "props": {"name": "cell"}})
    store.apply(
        {
            "op": "put_edge",
            "id": store.next_id("edge"),
            "type": "supplied_by",
            "roles": {"item": b, "source": a},
        }
    )
    assert len(store.edges[a]) == 1 and len(store.edges[b]) == 1
    assert store.edges[a][0].roles == {"item": b, "source": a}


def test_reopen_replays_wal(tmp_path):
    store = Store(tmp_path)
    nid = put_supplier(store, "Ionix", "KR")
    pos = store.apply({"op": "patch_node", "id": nid, "props": {"country": "JP"}})
    store2 = Store(tmp_path)
    assert store2.nodes[nid].props["country"] == "JP"
    assert store2.position == pos
    assert store2.next_id("supplier") != nid  # id counters survive


def test_snapshot_then_more_writes_then_reopen(tmp_path):
    store = Store(tmp_path)
    a = put_supplier(store, "VoltaChem")
    store.snapshot()
    assert store.wal_len() == 0
    b = put_supplier(store, "Ionix")
    store2 = Store(tmp_path)
    assert set(store2.nodes) == {a, b}
    assert store2.nodes[a].props["name"] == "VoltaChem"


def test_alias_resolve_chases_chain(tmp_path):
    store = Store(tmp_path)
    a = put_supplier(store, "A")
    b = put_supplier(store, "B")
    c = put_supplier(store, "C")
    store.apply({"op": "alias", "absorbed": b, "survivor": a})
    store.apply({"op": "alias", "absorbed": c, "survivor": b})
    assert store.resolve(c) == a
    assert store.resolve(a) == a


def test_lineage_and_distinct_and_dup_records(tmp_path):
    store = Store(tmp_path)
    a = put_supplier(store, "A")
    b = put_supplier(store, "B")
    store.apply(
        {
            "op": "lineage",
            "kind": "merge",
            "survivor": a,
            "absorbed": b,
            "pre_states": {},
        }
    )
    c = put_supplier(store, "C")
    store.apply({"op": "distinct", "a": a, "b": b, "reason": "different"})
    store.apply(
        {
            "op": "dup",
            "a": a,
            "b": c,
            "score": 0.9,
            "cls": "supplier",
            "evidence": "near name",
        }
    )
    # a distinct-suppressed pair never enters the ledger, even on replay
    store.apply(
        {
            "op": "dup",
            "a": a,
            "b": b,
            "score": 0.99,
            "cls": "supplier",
            "evidence": "near name",
        }
    )
    store2 = Store(tmp_path)
    assert store2.lineage[0]["kind"] == "merge"
    assert frozenset((a, b)) in store2.distinct_pairs
    assert len(store2.dup_ledger) == 1
    assert store2.dup_ledger[0]["score"] == 0.9


def test_retire_record(tmp_path):
    store = Store(tmp_path)
    a = put_supplier(store, "A")
    pos = store.apply({"op": "retire", "id": a, "reason": "gone"})
    assert store.nodes[a].retired_at == pos
    store2 = Store(tmp_path)
    assert store2.nodes[a].retired_at == pos

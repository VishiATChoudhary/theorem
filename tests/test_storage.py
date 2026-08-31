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
    store.close()
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
    store.close()
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
    store.close()
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
    store.close()
    store2 = Store(tmp_path)
    assert store2.nodes[a].retired_at == pos


def test_a_record_from_the_future_refuses_to_open(tmp_path):
    """The compatibility promise is that an unknown record is loud. Skipping
    it would apply every write around it and call the result the graph."""
    import json

    import pytest

    from theorem.engine.storage import StoreError

    store = Store(tmp_path)
    put_supplier(store, "VoltaChem")
    store.close()
    with (tmp_path / "wal.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"op": "teleport", "id": "#s-1", "_pos": 2}) + "\n")

    with pytest.raises(StoreError) as e:
        Store(tmp_path)
    assert "newer version" in str(e.value)


def test_a_store_written_by_an_earlier_release_still_opens(tmp_path):
    """Records are self-describing objects, so a log holding only the ops
    0.1 knew about must replay unchanged."""
    import json

    wal = tmp_path / "wal.jsonl"
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    wal.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {
                    "op": "put_node",
                    "id": "#s-1",
                    "cls": "supplier",
                    "props": {"name": "VoltaChem"},
                    "_pos": 1,
                },
                {
                    "op": "put_node",
                    "id": "#p-1",
                    "cls": "part",
                    "props": {"name": "Anode"},
                    "_pos": 2,
                },
                {
                    "op": "put_edge",
                    "id": "#e-1",
                    "type": "supplied_by",
                    "roles": {"item": "#p-1", "source": "#s-1"},
                    "_pos": 3,
                },
                {
                    "op": "patch_node",
                    "id": "#s-1",
                    "props": {"country": "DE"},
                    "_pos": 4,
                },
                {"op": "retire", "id": "#p-1", "reason": "gone", "_pos": 5},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    store = Store(tmp_path)
    assert store.nodes["#s-1"].props["country"] == "DE"
    assert store.nodes["#p-1"].retired_at == 5
    assert store.edge_index["#e-1"].type == "supplied_by"
    store.close()


def test_a_bulk_that_cannot_be_applied_writes_nothing(tmp_path):
    """Validating as it went committed the records before the bad one,
    which is the opposite of what the rest of the system promises."""
    import pytest

    from theorem.engine.storage import StoreError

    store = Store(tmp_path)
    good = {"op": "put_node", "id": "#s-1", "cls": "supplier", "props": {"name": "A"}}
    bad = {"op": "retire", "id": "#s-404", "reason": "no such node"}
    with pytest.raises(StoreError):
        store.bulk([good, bad])
    assert store.nodes == {}
    assert store.wal_len() == 0
    assert store.position == 0
    store.close()

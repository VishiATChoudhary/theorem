from theorem.engine import dedup


def test_block_key_normalizes():
    assert dedup.block_key("supplier", "Volta-Chem GmbH") == dedup.block_key("supplier", "voltachem")


def test_sync_candidates_same_block_only(fixture_store):
    store = fixture_store
    nid = store.next_id("supplier")
    store.apply({"op": "put_node", "id": nid, "cls": "supplier",
                 "props": {"name": "VoltaChem AG", "country": "DE"}})
    cands = dedup.sync_candidates(store, store.nodes[nid])
    assert len(cands) == 1
    assert cands[0]["a"] == store.ids["volta"]
    assert cands[0]["score"] >= 0.85


def test_cross_class_never_candidates(fixture_store):
    store = fixture_store
    nid = store.next_id("product")
    store.apply({"op": "put_node", "id": nid, "cls": "product",
                 "props": {"name": "VoltaChem", "launch_year": 2026}})
    assert dedup.sync_candidates(store, store.nodes[nid]) == []


def test_sweep_catches_cross_block_near_names(fixture_store):
    store = fixture_store
    # "The VoltaChem" blocks under "thevol", missed by sync blocking
    nid = store.next_id("supplier")
    store.apply({"op": "put_node", "id": nid, "cls": "supplier",
                 "props": {"name": "The VoltaChem", "country": "DE"}})
    assert dedup.sync_candidates(store, store.nodes[nid]) == []
    found = dedup.sweep(store)
    assert found >= 1
    pairs = [frozenset((r["a"], r["b"])) for r in store.dup_ledger]
    assert frozenset((store.ids["volta"], nid)) in pairs


def test_sweep_idempotent(fixture_store):
    store = fixture_store
    nid = store.next_id("supplier")
    store.apply({"op": "put_node", "id": nid, "cls": "supplier",
                 "props": {"name": "The VoltaChem", "country": "DE"}})
    dedup.sweep(store)
    n = len(store.dup_ledger)
    assert dedup.sweep(store) == 0
    assert len(store.dup_ledger) == n

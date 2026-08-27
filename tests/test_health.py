from theorem.engine import health
from theorem.engine.executor import ReadContext, execute_read
from theorem.parser import parse
from theorem.verifier import verify


def test_fresh_node_healthy(fixture_store):
    s = health.scores(fixture_store, fixture_store.ids["cell"])
    assert s["loss"] == 0 and s["query"] == 0
    assert 0 <= s["structure"] < 0.1 and s["staleness"] < 0.1


def test_flags_raise_query_score(fixture_store):
    cell = fixture_store.ids["cell"]
    for i in range(3):
        fixture_store.apply({"op": "flag", "id": cell, "reason": f"r{i}"})
    assert health.scores(fixture_store, cell)["query"] == 1.0


def test_conflicting_reasserts_raise_loss(fixture_store):
    cell = fixture_store.ids["cell"]
    for cost in (5.0, 6.0, 7.0, 8.0, 9.0):
        fixture_store.apply(
            {"op": "patch_node", "id": cell, "props": {"unit_cost": cost}}
        )
    assert health.scores(fixture_store, cell)["loss"] == 1.0


def test_orphan_structure_score(fixture_store):
    nid = fixture_store.next_id("supplier")
    fixture_store.apply(
        {
            "op": "put_node",
            "id": nid,
            "cls": "supplier",
            "props": {"name": "Lonely Corp", "country": "US"},
        }
    )
    assert health.scores(fixture_store, nid)["structure"] == 0.3


def test_supernode_structure_score(fixture_store):
    store = fixture_store
    hub = store.next_id("supplier")
    store.apply(
        {
            "op": "put_node",
            "id": hub,
            "cls": "supplier",
            "props": {"name": "MegaHub", "country": "CN"},
        }
    )
    for i in range(120):
        pid = store.next_id("part")
        store.apply(
            {
                "op": "put_node",
                "id": pid,
                "cls": "part",
                "props": {"name": f"widget {i}", "unit_cost": 1.0},
            }
        )
        store.apply(
            {
                "op": "put_edge",
                "id": store.next_id("edge"),
                "type": "supplied_by",
                "roles": {"item": pid, "source": hub},
            }
        )
    assert health.scores(store, hub)["structure"] == 1.0


def test_health_queryable_worklist(fixture_store, schema):
    cell = fixture_store.ids["cell"]
    for i in range(3):
        fixture_store.apply({"op": "flag", "id": cell, "reason": f"r{i}"})
    out = execute_read(
        verify(
            parse("find nodes where health.query > 0.5 as w\nreturn w.name"), schema
        ),
        fixture_store,
        schema,
        ReadContext(),
    )
    assert "lithium cell" in out and "results: 1 of 1" in out

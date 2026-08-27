import pytest

from theorem.engine.executor import ReadContext, execute_read
from theorem.engine.writes import WriteContext, execute_write
from theorem.parser import parse
from theorem.schema import Schema
from theorem.verifier import verify


@pytest.fixture
def wctx(fixture_store, schema):
    return WriteContext(store=fixture_store, schema=schema)


def type_env(wctx):
    env = {}
    for name, val in wctx.env.items():
        if isinstance(val, str) and val in wctx.store.nodes:
            env[name] = wctx.store.nodes[wctx.store.resolve(val)].cls
        else:
            env[name] = "nodes"
    return env


def run_writes(text, wctx):
    plans = verify(parse(text), wctx.schema, type_env(wctx))
    receipts = [execute_write(p.stmt, wctx) for p in plans]
    return receipts


def test_assert_receipt_and_dup_candidate(wctx):
    (r1,) = run_writes('assert part {name: "graphene sheet", unit_cost: 12.0} source doc:d/p3 as gs', wctx)
    out = r1.render()
    assert out.startswith("receipt: created part gs = #p-")
    assert "guards: schema ok, class invariants ok" in out
    (r2,) = run_writes('assert part {name: "graphene sheets", unit_cost: 11.8} source doc:d/p4 as gs2', wctx)
    out2 = r2.render()
    assert "dup candidates: 1" in out2
    assert "graphene sheet" in out2 and "score 0." in out2
    assert "resolve with: merge / distinct" in out2


def test_assert_edge_via_binding(wctx):
    run_writes('assert part {name: "x9", unit_cost: 1.0} as gs', wctx)
    (r,) = run_writes(f'assert edge supplied_by(item: gs, source: {wctx.store.ids["volta"]})', wctx)
    assert "created edge supplied_by" in r.render()


def test_merge_alias_and_lineage(wctx):
    store = wctx.store
    a, b = store.ids["ionix_kr"], store.ids["ionix_jp"]
    (r,) = run_writes(f"merge {a}, {b} prefer newest", wctx)
    out = r.render()
    assert "merged" in out and "lineage keeps both" in out
    survivor = store.resolve(b)
    assert survivor == a  # older id survives
    # absorbed node's edges reachable through survivor
    kinds = [rec["kind"] for rec in store.lineage]
    assert "merge" in kinds
    # prefer newest: JP country (b is newer) wins on conflict
    assert store.nodes[a].props["country"] == "JP"


def test_merge_unwindable_state_recorded(wctx):
    store = wctx.store
    a, b = store.ids["ionix_kr"], store.ids["ionix_jp"]
    run_writes(f"merge {a}, {b}", wctx)
    rec = [r for r in store.lineage if r["kind"] == "merge"][0]
    assert rec["pre_states"][a]["props"]["country"] == "KR"
    assert rec["pre_states"][b]["props"]["country"] == "JP"


def test_distinct_suppresses(wctx):
    run_writes('assert supplier {name: "Volta Chem", country: "DE"} as v2', wctx)
    store = wctx.store
    assert store.dup_ledger, "near-name assert should queue a candidate"
    a, b = store.dup_ledger[-1]["a"], store.dup_ledger[-1]["b"]
    (r,) = run_writes(f'distinct {a}, {b} reason "different companies"', wctx)
    assert "distinct" in r.render()
    ctx = ReadContext()
    out = execute_read(verify(parse("find dup_candidates as d\nreturn d.a, d.b"), wctx.schema), store, wctx.schema, ctx)
    assert a not in out
    # and a re-assert of the same near-name does not resurface the pair
    receipts = run_writes('assert supplier {name: "VoltaChem GmbH", country: "DE"} as v3', wctx)
    assert all(frozenset((a, b)) != frozenset((c["a"], c["b"]))
               for c in receipts[0].dup_candidates)


def test_refine_csv_blob(wctx, tmp_path):
    store = wctx.store
    att_dir = store.path / "attachments"
    att_dir.mkdir()
    (att_dir / "csv-1.csv").write_text("component,eur_unit\nbolt,0.1\nnut,0.05\nscrew,0.2\n")
    run_writes('assert table_blob {title: "prices", payload: attach:csv-1} source doc:r as prices', wctx)
    (r,) = run_writes('refine prices into part\n  with {name: col "component", unit_cost: col "eur_unit"}\n  as price_parts', wctx)
    out = r.render()
    assert "refined" in out and "3 part nodes" in out
    assert "lineage: each new node carries origin" in out
    blob_id = [n.id for n in store.nodes.values() if n.cls == "table_blob"][0]
    children = [n for n in store.nodes.values() if n.origin == blob_id]
    assert len(children) == 3
    assert store.nodes[blob_id].state == "composite"
    assert children[0].props["unit_cost"] == 0.1


def test_compact(wctx):
    ctx = ReadContext()
    # bind old parts then compact them into a summary node
    plans = verify(parse('find part where unit_cost < 3 as cheap\ncompact cheap as summary {name: "cheap parts 2026", unit_cost: 1.5}'), wctx.schema)
    execute_read(plans[:1], wctx.store, wctx.schema, ctx)
    # executor binds; write executor needs the binding: WriteContext env carries it
    wctx.env["cheap"] = [n.id for n in wctx.store.nodes.values()
                         if n.cls == "part" and n.props["unit_cost"] < 3]
    r = execute_write(plans[1].stmt, wctx)
    out = r.render()
    assert "compacted" in out
    summary = [n for n in wctx.store.nodes.values() if n.props.get("name") == "cheap parts 2026"]
    assert len(summary) == 1 and summary[0].state == "composite"
    for nid in wctx.env["cheap"]:
        assert wctx.store.nodes[nid].retired_at is not None


def test_retire_and_flag(wctx):
    store = wctx.store
    sid = store.ids["ionix_jp"]
    (r,) = run_writes(f'retire {sid} reason "acquired"', wctx)
    assert "retired" in r.render()
    assert store.nodes[sid].retired_at is not None
    (f,) = run_writes(f'flag {store.ids["cell"]} reason "wrong chemistry"', wctx)
    assert "flagged" in f.render()
    assert store.nodes[store.ids["cell"]].flags == ["wrong chemistry"]


def test_derive_class_provisional(wctx):
    (r,) = run_writes("derive class distributor from supplier with {region: str}", wctx)
    out = r.render()
    assert "class distributor provisional" in out
    assert "quota: 500 instances" in out
    cdef = wctx.schema.classes["distributor"]
    assert cdef.status == "provisional" and cdef.base == "supplier"
    # new class immediately usable
    run_writes('assert distributor {name: "EuroParts", country: "FR", region: "EU"} as d', wctx)


def test_derive_similar_class_note(wctx):
    run_writes("derive class distributor from supplier with {region: str}", wctx)
    (r,) = run_writes("derive class distributer from supplier with {region: str}", wctx)
    assert "similar existing class" in r.render()


def test_merge_prefer_source_neither_matches_errors(wctx):
    from theorem.engine.writes import WriteError
    a, b = wctx.store.ids["ionix_kr"], wctx.store.ids["ionix_jp"]
    plans = verify(parse(f"merge {a}, {b} prefer source doc:nowhere"), wctx.schema)
    with pytest.raises(WriteError):
        execute_write(plans[0].stmt, wctx)


def test_self_merge_error_suggests_dup_candidate(wctx):
    from theorem.engine.writes import WriteError
    # identical re-assert: candidate lands in ledger, binding points at new node
    run_writes('assert supplier {name: "Volta Chem GmbH", country: "DE"} as v1', wctx)
    run_writes('assert supplier {name: "Volta Chem GmbH", country: "DE"} as v1x', wctx)
    new_id = wctx.env["v1x"]
    old_id = wctx.env["v1"]
    plans = verify(parse(f"merge {new_id}, {new_id}"), wctx.schema)
    with pytest.raises(WriteError) as e:
        execute_write(plans[0].stmt, wctx)
    msg = str(e.value)
    assert "itself" in msg
    assert old_id in msg and "merge" in msg  # concrete resolving command suggested

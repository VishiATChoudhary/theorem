from graphlang.schema import Schema
from graphlang.session import Session


def make_session(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def test_schema_statement(tmp_path):
    s = make_session(tmp_path)
    out = s.run("schema")
    assert "supplied_by(item: part, source: supplier)" in out


def test_construction_session_end_to_end(tmp_path):
    s = make_session(tmp_path)

    out = s.run('assert supplier {name: "Ionix Co", country: "KR"}\n  source doc:report-08/p1 as ionix')
    assert "receipt: created supplier ionix = #s-1" in out

    out = s.run('assert supplier {name: "Ionix"} source doc:report-08/p2 as ionix2')
    assert "dup candidates: 1" in out and "resolve with: merge / distinct" in out

    out = s.run("merge ionix, ionix2 prefer newest")
    assert "merged -> #s-1" in out

    # writes visible to reads, alias transparent
    out = s.run('find supplier as sups\nreturn sups.name')
    assert "results: 1 of 1" in out

    # blob ingest + refine
    att = s.store.path / "attachments"
    att.mkdir()
    (att / "q3.csv").write_text("item,unit_eur\nanode,2.5\ncathode,3.5\n")
    out = s.run('assert table_blob {title: "Ionix price list Q3", payload: attach:q3}\n  source doc:report-08/p4 as pricelist')
    assert "created table_blob pricelist" in out

    out = s.run('refine pricelist into part\n  with {name: col "item", unit_cost: col "unit_eur"} as rows')
    assert "-> 2 part nodes" in out

    out = s.run("find part as p\nreturn p.name, p.unit_cost order by p.unit_cost")
    assert "anode, 2.5" in out and "cathode, 3.5" in out

    # bindings from reads usable by writes in the same run
    out = s.run('find part where unit_cost < 3 as cheap\ncompact cheap as agg {name: "cheap summary", unit_cost: 2.5}')
    assert "compacted 1 part nodes" in out


def test_verify_error_stops_everything(tmp_path):
    s = make_session(tmp_path)
    out = s.run('assert supplier {name: "A"} as a\nfind vendor as v')
    assert "nothing was executed." in out
    assert not s.store.nodes  # first statement did not run either


def test_flag_then_worklist(tmp_path):
    s = make_session(tmp_path)
    s.run('assert supplier {name: "X Corp", country: "DE"} as x')
    s.run("flag #s-1 reason \"stale\"")
    s.run("flag #s-1 reason \"stale2\"")
    s.run("flag #s-1 reason \"stale3\"")
    out = s.run("find nodes where health.query > 0.5 as w\nreturn w.name")
    assert "X Corp" in out


def test_derive_then_use(tmp_path):
    s = make_session(tmp_path)
    out = s.run("derive class broker from supplier with {takes_inventory: bool}")
    assert "provisional" in out
    out = s.run('assert broker {name: "MidCo", takes_inventory: true} as m')
    assert "created broker" in out
    out = s.run("find broker as b\nreturn b.name")
    assert "MidCo" in out


def test_parse_error_reported_not_raised(tmp_path):
    s = make_session(tmp_path)
    out = s.run("frobnicate everything")
    assert "parse error" in out and "nothing was executed." in out

import pytest

from graphlang.parser import parse
from graphlang.schema import Schema
from graphlang.verifier import VerifyError, verify

S = Schema.supply_chain()

Q2_TEXT = """\
find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts budget 2000 tokens
"""


def err(text):
    with pytest.raises(VerifyError) as e:
        verify(parse(text), S)
    return str(e.value)


def test_q2_verifies():
    plans = verify(parse(Q2_TEXT), S)
    assert len(plans) == 6


def test_unknown_class_suggests():
    msg = err('find vendor where name = "x" as v')
    assert "did you mean" in msg and "supplier" in msg
    assert msg.rstrip().endswith("nothing was executed.")
    assert "line 1" in msg


def test_unknown_edge_suggests():
    msg = err('find part as p\nfollow p supplied_byy source as s')
    assert "supplied_by" in msg and "line 2" in msg


def test_unknown_role():
    msg = err('find part as p\nfollow p supplied_by dest as s')
    assert "role" in msg and "source" in msg


def test_arrival_role_is_own_role():
    # parts already occupies the item role; arriving at item is a type error
    msg = err("find part as parts\nfollow parts supplied_by item as x")
    assert "item" in msg and ("already" in msg or "type" in msg)


def test_unknown_property_in_where():
    msg = err("find product where launch_yr > 2024 as r")
    assert "launch_year" in msg


def test_unbound_follow_source():
    msg = err("follow ghosts uses component as parts")
    assert "ghosts" in msg and ("unbound" in msg or "not bound" in msg)


def test_aggregate_needs_group():
    msg = err("find part as p\ncount distinct p.name as n")
    assert "group" in msg


def test_duplicate_binding_rejected():
    msg = err("find part as p\nfind supplier as p")
    assert "p" in msg and "already" in msg


def test_return_unbound_column():
    msg = err("find part as p\nreturn q.name")
    assert "q" in msg


def test_health_columns_allowed_on_nodes():
    verify(parse("find nodes where health.loss > 0.8 as w\nreturn w.class, w.health limit 10"), S)


def test_dup_candidates_target():
    verify(parse("find dup_candidates where class = supplier order by score as d\nreturn d.score"), S)


def test_write_bindings_thread_forward():
    text = (
        'assert part {name: "x", unit_cost: 1.0} source doc:d as gs\n'
        "assert edge supplied_by(item: gs, source: #s-1)\n"
        "merge gs, #s-1 prefer newest\n"
    )
    verify(parse(text), S)


def test_assert_unknown_prop():
    msg = err('assert part {nam: "x"} as gs')
    assert "name" in msg  # suggestion


def test_assert_edge_wrong_roles():
    msg = err('assert part {name: "x"} as gs\nassert edge supplied_by(item: gs, target: gs)')
    assert "target" in msg


def test_derive_unknown_base():
    msg = err("derive class broker from suplier with {takes_inventory: bool}")
    assert "supplier" in msg

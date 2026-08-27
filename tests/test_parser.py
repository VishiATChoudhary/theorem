import pytest

from theorem.ast_nodes import (
    Aggregate,
    AssertEdge,
    AssertNode,
    Clause,
    Compact,
    Continue,
    DeriveClass,
    Distinct,
    Find,
    Flag,
    Follow,
    GroupBy,
    Merge,
    Refine,
    Retire,
    Return,
    SchemaStmt,
)
from theorem.parser import ParseError, parse

Q1_TEXT = """\
find part where name = "lithium cell" as cell
follow cell supplied_by source as sups
return sups.name
"""

Q2_TEXT = """\
find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts budget 2000 tokens
"""


def test_q1_parses():
    stmts = parse(Q1_TEXT)
    assert [type(s) for s in stmts] == [Find, Follow, Return]
    f = stmts[0]
    assert f.target == "part" and f.name == "cell"
    assert f.cond == [("and", Clause(("name",), "=", "lithium cell"))]
    fo = stmts[1]
    assert (fo.src, fo.edge, fo.role, fo.name) == ("cell", "supplied_by", "source", "sups")
    ret = stmts[2]
    assert ret.cols == [("sups", "name")]
    assert ret.budget == 2000  # default
    assert ret.limit is None and ret.order_by is None


def test_q2_parses():
    stmts = parse(Q2_TEXT)
    assert [type(s).__name__ for s in stmts] == [
        "Find", "Follow", "Follow", "GroupBy", "Aggregate", "Return"]
    g = stmts[3]
    assert g.col == ("sups",) and g.name == "g"
    agg = stmts[4]
    assert agg.op == "count" and agg.distinct and agg.col == ("g", "parts")
    assert agg.name == "n_parts"
    ret = stmts[5]
    assert ret.budget == 2000 and ret.order_by == ("n_parts",) and not ret.desc


def test_group_by_value_spelling():
    (g,) = parse("group by sups.country as by_country")
    assert g.col == ("sups", "country") and g.name == "by_country"


def test_where_and_or():
    (f,) = parse('find part where unit_cost > 4 and unit_cost < 10 or name contains "cell" as p')
    assert f.cond[0] == ("and", Clause(("unit_cost",), ">", 4))
    assert f.cond[1] == ("and", Clause(("unit_cost",), "<", 10))
    assert f.cond[2] == ("or", Clause(("name",), "contains", "cell"))


def test_find_special_targets():
    (f,) = parse("find dup_candidates where class = supplier order by score as dups")
    assert f.target == "dup_candidates" and f.name == "dups"
    assert f.cond == [("and", Clause(("class",), "=", "supplier"))]
    assert f.order_by == ("score",) and not f.desc
    (f2,) = parse("find nodes where health.structure > 0.7 as worklist")
    assert f2.order_by is None


def test_find_nodes_health():
    (f,) = parse("find nodes where health.loss > 0.8 as worklist")
    assert f.target == "nodes"
    assert f.cond == [("and", Clause(("health", "loss"), ">", 0.8))]


def test_continuation_lines_join():
    stmts = parse('assert part {name: "x", unit_cost: 12.0}\n  source doc:d/p3 as gs')
    assert len(stmts) == 1
    a = stmts[0]
    assert type(a) is AssertNode
    assert a.cls == "part" and a.name == "gs" and a.source == "doc:d/p3"
    assert a.props == {"name": "x", "unit_cost": 12.0}


def test_assert_edge():
    (e,) = parse("assert edge supplied_by(item: gs, source: voltachem)\n  source doc:d/p3")
    assert type(e) is AssertEdge
    assert e.edge == "supplied_by"
    assert e.role_refs == {"item": "gs", "source": "voltachem"}
    assert e.source == "doc:d/p3"


def test_merge_and_distinct():
    (m,) = parse("merge gs, #p-71002 prefer newest")
    assert (m.a, m.b, m.policy) == ("gs", "#p-71002", "newest")
    (m2,) = parse("merge a, b")
    assert m2.policy == "newest"  # default
    (d,) = parse('distinct gs, #p-71002 reason "different SKUs"')
    assert (d.a, d.b, d.reason) == ("gs", "#p-71002", "different SKUs")


def test_refine():
    (r,) = parse('refine prices into part\n  with {name: col "component", unit_cost: col "eur_unit"}\n  as price_parts')
    assert type(r) is Refine
    assert r.ref == "prices" and r.into_cls == "part" and r.name == "price_parts"
    assert r.mapping == {"name": "component", "unit_cost": "eur_unit"}


def test_compact():
    (c,) = parse('compact old_quotes as summary_quote\n  {period: "2024", mean_cost: 3.1}')
    assert type(c) is Compact
    assert c.src == "old_quotes" and c.name == "summary_quote"
    assert c.props == {"period": "2024", "mean_cost": 3.1}


def test_retire_flag():
    (r,) = parse('retire #s-1120 reason "acquired by VoltaChem"')
    assert type(r) is Retire and r.ref == "#s-1120"
    (f,) = parse('flag #p-88231 reason "wrong supplier"')
    assert type(f) is Flag and f.ref == "#p-88231" and f.reason == "wrong supplier"


def test_derive_class():
    (d,) = parse("derive class broker from supplier\n  with {takes_inventory: bool}")
    assert type(d) is DeriveClass
    assert d.name == "broker" and d.base == "supplier"
    assert d.props == {"takes_inventory": "bool"}


def test_schema_and_continue():
    (s,) = parse("schema")
    assert type(s) is SchemaStmt
    (c,) = parse("continue @c81f budget 1500 tokens")
    assert type(c) is Continue and c.handle == "@c81f" and c.budget == 1500


def test_return_full_clause():
    (r,) = parse("return sups.name, n_parts order by n_parts desc limit 10 budget 500 tokens after @t-42")
    assert r.cols == [("sups", "name"), ("n_parts",)]
    assert r.order_by == ("n_parts",) and r.desc
    assert r.limit == 10 and r.budget == 500 and r.after == "@t-42"


def test_comment_and_blank_lines():
    stmts = parse("# a comment\n\nschema\n")
    assert len(stmts) == 1


def test_line_numbers():
    stmts = parse("schema\nfind part as p\nreturn p.name")
    assert [s.line for s in stmts] == [1, 2, 3]


def test_bool_literal():
    (a,) = parse("assert broker {takes_inventory: true} as b")
    assert a.props == {"takes_inventory": True}


@pytest.mark.parametrize("bad,msg_part", [
    ("frobnicate part as p", "unknown verb"),
    ("find part where name = as p", "expected"),
    ("find part where name = \"x\"", "as"),
    ("follow a b as c", "expected"),
    ("merge onlyone", "expected"),
])
def test_parse_errors(bad, msg_part):
    with pytest.raises(ParseError) as e:
        parse(bad)
    assert msg_part in str(e.value).lower()


def test_parse_error_carries_line():
    with pytest.raises(ParseError) as e:
        parse("schema\nfrobnicate part as p")
    assert e.value.line_no == 2


# regression tests from adversarial review round 1

def test_bare_word_not_a_prop_literal():
    with pytest.raises(ParseError):
        parse("assert part {status: active} as p")


def test_doc_provenance_not_a_literal():
    with pytest.raises(ParseError):
        parse("assert part {ref: doc:xyz} as p")


def test_bare_word_ok_in_condition():
    (f,) = parse("find dup_candidates where class = supplier as d")
    assert f.cond[0][1].value == "supplier"


def test_col_max_three_segments():
    with pytest.raises(ParseError):
        parse("return a.b.c.d")
    with pytest.raises(ParseError):
        parse("return a..b")


def test_assert_edge_exactly_two_roles():
    with pytest.raises(ParseError):
        parse("assert edge uses(whole: x)")
    with pytest.raises(ParseError):
        parse("assert edge uses(whole: x, component: y, extra: z)")


def test_indented_comment_skipped_but_nodeid_continuation_kept():
    stmts = parse('assert part {name: "x"}\n  # a comment\n  as p')
    assert stmts[0].name == "p"
    (m,) = parse("merge gs,\n  #p-71002 prefer newest")
    assert m.b == "#p-71002"

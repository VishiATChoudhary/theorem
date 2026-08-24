from graphlang.engine.executor import ReadContext, execute_read
from graphlang.parser import parse
from graphlang.schema import Schema
from graphlang.verifier import verify

S = Schema.supply_chain()

Q1 = """\
find part where name = "lithium cell" as cell
follow cell supplied_by source as sups
return sups.name
"""

Q2 = """\
find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts desc budget 2000 tokens
"""


def run(text, store, ctx=None):
    ctx = ctx or ReadContext()
    return execute_read(verify(parse(text), S), store, S, ctx)


def test_q1_two_suppliers(fixture_store):
    out = run(Q1, fixture_store)
    assert "VoltaChem" in out and "Ionix" in out
    assert "results: 2 of 2, complete" in out


def test_q2_group_by_identity_not_name(fixture_store):
    out = run(Q2, fixture_store)
    # GridPack(2026): cell+casing; PowerBank(2025): cell+wire
    # cell -> VoltaChem + Ionix/KR; wire -> Ionix/KR; casing -> Ionix/JP
    # so: Ionix/KR supplies 2 distinct parts, VoltaChem 1, Ionix/JP 1
    lines = [l for l in out.splitlines() if "," in l and "results" not in l and "columns" not in l]
    assert lines[0] == "Ionix, 2"
    rest = set(lines[1:])
    assert rest == {"VoltaChem, 1", "Ionix, 1"}  # two Ionix rows: identity grouping


def test_group_by_value_merges(fixture_store):
    text = """\
find supplier as sups
group by sups.country as g
count g.sups as n
return g.key, n order by g.key
"""
    out = run(text, fixture_store)
    lines = [l for l in out.splitlines() if "," in l and "results" not in l and "columns" not in l]
    assert lines == ["DE, 1", "JP, 1", "KR, 1"]


def test_where_and_or_contains(fixture_store):
    out = run('find part where unit_cost > 2 and name contains "cell" as p\nreturn p.name', fixture_store)
    assert "lithium cell" in out and "casing" not in out


def test_order_and_limit(fixture_store):
    out = run("find part as p\nreturn p.name order by p.unit_cost desc limit 2", fixture_store)
    lines = [l for l in out.splitlines()[2:] if l]
    assert lines == ["solar film", "lithium cell"]
    assert "results: 2 of 4" in out


def test_budget_truncation_and_continue(fixture_store):
    ctx = ReadContext()
    out = run("find part as p\nreturn p.name, p.unit_cost order by p.unit_cost budget 20 tokens", fixture_store, ctx)
    assert "budget hit" in out
    assert "resume with: continue @c" in out
    handle = out.rsplit("continue ", 1)[1].strip()
    out2 = run(f"continue {handle} budget 2000 tokens", fixture_store, ctx)
    total = out + out2
    for name in ["copper wire", "casing", "lithium cell", "solar film"]:
        assert name in total
    assert "complete" in out2


def test_empty_result(fixture_store):
    out = run("find product where launch_year > 2030 as p\nreturn p.name", fixture_store)
    assert "results: 0 of 0, complete" in out


def test_find_nodes_any_class(fixture_store):
    out = run("find nodes where name contains \"Ionix\" as n\nreturn n.class, n.name", fixture_store)
    assert out.count("supplier") == 2


def test_retired_excluded(fixture_store):
    sid = fixture_store.ids["ionix_jp"]
    fixture_store.apply({"op": "retire", "id": sid, "reason": "gone"})
    out = run("find supplier as s\nreturn s.name", fixture_store)
    assert "results: 2 of 2" in out


def test_incident_rendering(fixture_store):
    out = run('find part where name = "lithium cell" as cell\nreturn cell', fixture_store)
    assert 'part "lithium cell" {unit_cost: 4.2}' in out
    assert "supplied_by -> supplier" in out
    assert "uses <- product" in out


def test_traffic_recorded(fixture_store):
    cell = fixture_store.ids["cell"]
    before = fixture_store.nodes[cell].traffic
    run(Q1, fixture_store)
    assert fixture_store.nodes[cell].traffic > before


def test_follow_with_where(fixture_store):
    text = """\
find product where launch_year > 2024 as recent
follow recent uses component where unit_cost > 3 as parts
return parts.name
"""
    out = run(text, fixture_store)
    assert "lithium cell" in out and "copper wire" not in out and "casing" not in out


def test_global_count_distinct(fixture_store):
    out = run("find supplier as s\ncount distinct s as n\nreturn n", fixture_store)
    assert "results: 1 of 1" in out
    assert out.splitlines()[-1] == "3"


def test_global_avg_prop(fixture_store):
    out = run("find part as p\navg p.unit_cost as m\nreturn m", fixture_store)
    assert out.splitlines()[-1] == "3.7"  # (4.2+1.1+7.5+2.0)/4


def test_trail_semantics_excludes_backtrack(fixture_store):
    # products sharing a part with PowerBank Pro, excluding itself via
    # edge-uniqueness (same uses edge cannot be walked twice in a row)
    text = """\
find product where name = "PowerBank Pro" as pb
follow pb uses component as parts
follow parts uses whole as others
return others.name
"""
    out = run(text, fixture_store)
    assert "GridPack" in out            # shares lithium cell
    assert "PowerBank Pro" not in out   # backtrack over same edge excluded

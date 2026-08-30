"""Transitive traversal: `follow ... upto N` and `upto any`.

The questions technical graphs are built to answer are about reach. What
does this assembly contain, all the way down. What breaks if this changes.
A single `follow` cannot express any of them.

The fixture is a small bill of materials with a deliberate cycle, because
real dependency graphs have them and traversal has to terminate anyway.
"""

import pytest

from theorem.engine.executor import execute_rows
from theorem.engine.storage import Store
from theorem.parser import ParseError, parse
from theorem.schema import ClassDef, EdgeDef, Schema
from theorem.verifier import VerifyError, verify


def _schema():
    s = Schema()
    s.classes["item"] = ClassDef(
        name="item", props={"name": "str", "unit_cost": "float"}
    )
    s.edges["contains"] = EdgeDef(
        name="contains", roles={"whole": "item", "part": "item"}
    )
    return s


@pytest.fixture
def bom(tmp_path):
    """car -> engine -> piston -> ring, engine -> bolt, and a cycle
    between two mutually-referencing spec documents."""
    schema = _schema()
    store = Store(tmp_path / "db")
    ids = {}
    for name, cost in [
        ("car", 30000.0),
        ("engine", 5000.0),
        ("piston", 120.0),
        ("ring", 4.0),
        ("bolt", 1.0),
        ("specA", 0.0),
        ("specB", 0.0),
    ]:
        nid = store.next_id("item")
        store.apply(
            {
                "op": "put_node",
                "id": nid,
                "cls": "item",
                "props": {"name": name, "unit_cost": cost},
            }
        )
        ids[name] = nid
    for whole, part in [
        ("car", "engine"),
        ("engine", "piston"),
        ("piston", "ring"),
        ("engine", "bolt"),
        ("specA", "specB"),
        ("specB", "specA"),
    ]:
        store.apply(
            {
                "op": "put_edge",
                "id": store.next_id("edge"),
                "type": "contains",
                "roles": {"whole": ids[whole], "part": ids[part]},
            }
        )
    store.ids = ids
    return store, schema


def run(text, bom):
    store, schema = bom
    return execute_rows(verify(parse(text), schema), store, schema)


def names(rows):
    return sorted(r[0] for r in rows)


# ---- bounded depth ----------------------------------------------------


def test_one_hop_unchanged_without_upto(bom):
    rows = run(
        'find item where name = "car" as c\n'
        "follow c contains part as p\n"
        "return p.name",
        bom,
    )
    assert names(rows) == ["engine"]


def test_upto_two_reaches_two_levels(bom):
    rows = run(
        'find item where name = "car" as c\n'
        "follow c contains part upto 2 as p\n"
        "return p.name",
        bom,
    )
    assert names(rows) == ["bolt", "engine", "piston"]


def test_upto_any_reaches_the_whole_subtree(bom):
    rows = run(
        'find item where name = "car" as c\n'
        "follow c contains part upto any as p\n"
        "return p.name",
        bom,
    )
    assert names(rows) == ["bolt", "engine", "piston", "ring"]


def test_upto_one_is_a_plain_follow(bom):
    plain = run(
        'find item where name = "car" as c\n'
        "follow c contains part as p\nreturn p.name",
        bom,
    )
    upto = run(
        'find item where name = "car" as c\n'
        "follow c contains part upto 1 as p\nreturn p.name",
        bom,
    )
    assert plain == upto


# ---- direction is still by role, not by arrow ------------------------


def test_transitive_the_other_way(bom):
    """What is this ring part of, all the way up."""
    rows = run(
        'find item where name = "ring" as r\n'
        "follow r contains whole upto any as owner\n"
        "return owner.name",
        bom,
    )
    assert names(rows) == ["car", "engine", "piston"]


# ---- cycles terminate -------------------------------------------------


def test_a_cycle_terminates_and_does_not_repeat(bom):
    rows = run(
        'find item where name = "specA" as a\n'
        "follow a contains part upto any as reached\n"
        "return reached.name",
        bom,
    )
    assert names(rows) == ["specA", "specB"]


# ---- filtering --------------------------------------------------------


def test_where_filters_arrivals_at_every_depth(bom):
    """Cheap parts anywhere in the car. The filter must not stop the walk
    at the engine, which is expensive but contains cheap things."""
    rows = run(
        'find item where name = "car" as c\n'
        "follow c contains part upto any where unit_cost < 100 as cheap\n"
        "return cheap.name",
        bom,
    )
    assert names(rows) == ["bolt", "ring"]


# ---- composes with the rest of the language --------------------------


def test_counts_over_a_transitive_reach(bom):
    rows = run(
        'find item where name = "car" as c\n'
        "follow c contains part upto any as p\n"
        "count distinct p as n\n"
        "return n",
        bom,
    )
    assert rows == [[4]]


def test_transitive_then_another_follow(bom):
    rows = run(
        'find item where name = "car" as c\n'
        "follow c contains part upto 2 as sub\n"
        "follow sub contains part as leaf\n"
        "return leaf.name",
        bom,
    )
    assert names(rows) == ["bolt", "piston", "ring"]


# ---- errors -----------------------------------------------------------


def test_upto_zero_is_rejected():
    with pytest.raises(ParseError):
        parse("find item as i\nfollow i contains part upto 0 as p\nreturn p.name")


def test_upto_needs_a_bound():
    with pytest.raises(ParseError):
        parse("find item as i\nfollow i contains part upto as p\nreturn p.name")


def test_unknown_role_still_caught(bom):
    _, schema = bom
    with pytest.raises(VerifyError):
        verify(
            parse(
                "find item as i\nfollow i contains bogus upto any as p\nreturn p.name"
            ),
            schema,
        )

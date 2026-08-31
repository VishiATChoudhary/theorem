"""A condition may name the binding its own statement creates."""

import pytest

from theorem.engine.executor import execute_rows
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.schema import ClassDef, EdgeDef, Schema
from theorem.verifier import VerifyError, verify


def _schema():
    s = Schema()
    s.classes["river"] = ClassDef("river", {"name": "str"})
    s.classes["lake"] = ClassDef("lake", {"name": "str", "area_km2": "float"})
    s.edges["feeds"] = EdgeDef("feeds", {"river": "river", "lake": "lake"})
    return s


@pytest.fixture
def graph(tmp_path):
    schema = _schema()
    store = Store(tmp_path / "db")
    ids = {}
    for cls, props in [
        ("river", {"name": "Natara"}),
        ("lake", {"name": "Small", "area_km2": 10.0}),
        ("lake", {"name": "Big", "area_km2": 900.0}),
    ]:
        nid = store.next_id(cls)
        store.apply({"op": "put_node", "id": nid, "cls": cls, "props": props})
        ids[props["name"]] = nid
    for lake in ("Small", "Big"):
        store.apply(
            {
                "op": "put_edge",
                "id": store.next_id("edge"),
                "type": "feeds",
                "roles": {"river": ids["Natara"], "lake": ids[lake]},
            }
        )
    yield store, schema
    store.close()


def run(text, graph):
    store, schema = graph
    return sorted(execute_rows(verify(parse(text), schema), store, schema))


def test_a_follow_condition_may_name_its_own_binding(graph):
    qualified = run(
        'find river where name = "Natara" as r\n'
        "follow r feeds lake as l where l.area_km2 < 100\n"
        "return l.name",
        graph,
    )
    bare = run(
        'find river where name = "Natara" as r\n'
        "follow r feeds lake where area_km2 < 100 as l\n"
        "return l.name",
        graph,
    )
    assert qualified == bare == [["Small"]]


def test_a_find_condition_may_name_its_own_binding(graph):
    assert run("find lake as l where l.area_km2 > 100\nreturn l.name", graph) == [
        ["Big"]
    ]


def test_the_qualified_form_still_checks_the_property(graph):
    _, schema = graph
    with pytest.raises(VerifyError) as e:
        verify(parse("find lake as l where l.aera_km2 > 100\nreturn l.name"), schema)
    assert "area_km2" in str(e.value)


def test_another_binding_is_not_stripped(graph):
    """Only the statement's own name is the arrival node; anything else
    keeps meaning what it meant."""
    _, schema = graph
    with pytest.raises(VerifyError):
        verify(
            parse(
                'find river where name = "Natara" as r\n'
                "follow r feeds lake as l where r.area_km2 < 100\n"
                "return l.name"
            ),
            schema,
        )


def test_via_is_untouched(graph):
    _, schema = graph
    verify(
        parse(
            'find river where name = "Natara" as r\n'
            "follow r feeds lake as l where l.area_km2 < 100\n"
            "return l.name"
        ),
        schema,
    )


def test_order_by_may_name_its_own_binding(graph):
    """`order by` sits in the same statement and reads the same node."""
    assert run("find lake as l order by l.area_km2 desc\nreturn l.name", graph) == [
        ["Big"],
        ["Small"],
    ]


def test_order_by_before_as_still_works(graph):
    assert run("find lake order by area_km2 desc as l\nreturn l.name", graph) == [
        ["Big"],
        ["Small"],
    ]

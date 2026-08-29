"""Relation labels that connect more than one pair of entity labels.

CypherBench graphs reuse a relation label across different endpoint
types: geography has `locatedIn` for DrainageBasin/Lake/Mountain to
Country and also Country to Continent. Keying theorem edge types by
label alone collapses those to whichever came last, which both hides
most of the graph from the schema the model is shown and leaves edge
instances carrying role names the schema does not declare.
"""

import json

import pytest

from eval.load_graph import derive_schema, load
from theorem.engine.executor import execute_rows
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.verifier import verify

SCHEMA = {
    "name": "geo",
    "entities": [
        {"label": "Mountain", "properties": {"elevation_m": "float"}},
        {"label": "Lake", "properties": {}},
        {"label": "Country", "properties": {}},
        {"label": "Continent", "properties": {}},
        {"label": "River", "properties": {}},
    ],
    "relations": [
        {"label": "locatedIn", "subj_label": "Mountain", "obj_label": "Country",
         "properties": {}},
        {"label": "locatedIn", "subj_label": "Lake", "obj_label": "Country",
         "properties": {}},
        {"label": "locatedIn", "subj_label": "Country", "obj_label": "Continent",
         "properties": {}},
        {"label": "flowsInto", "subj_label": "River", "obj_label": "River",
         "properties": {}},
    ],
}

KG = {
    "schema": SCHEMA,
    "entities": [
        {"eid": "Mountain#1", "label": "Mountain", "name": "K2",
         "properties": {"elevation_m": 8611.0}},
        {"eid": "Lake#1", "label": "Lake", "name": "Lake Geneva", "properties": {}},
        {"eid": "Country#1", "label": "Country", "name": "Pakistan", "properties": {}},
        {"eid": "Country#2", "label": "Country", "name": "Switzerland",
         "properties": {}},
        {"eid": "Continent#1", "label": "Continent", "name": "Asia", "properties": {}},
        {"eid": "River#1", "label": "River", "name": "Aare", "properties": {}},
        {"eid": "River#2", "label": "River", "name": "Rhine", "properties": {}},
    ],
    "relations": [
        {"rid": "0", "label": "locatedIn", "subj_id": "Mountain#1",
         "obj_id": "Country#1", "properties": {}},
        {"rid": "1", "label": "locatedIn", "subj_id": "Lake#1",
         "obj_id": "Country#2", "properties": {}},
        {"rid": "2", "label": "locatedIn", "subj_id": "Country#1",
         "obj_id": "Continent#1", "properties": {}},
        {"rid": "3", "label": "flowsInto", "subj_id": "River#1",
         "obj_id": "River#2", "properties": {}},
    ],
}


@pytest.fixture
def loaded(tmp_path):
    path = tmp_path / "geo.json"
    path.write_text(json.dumps(KG))
    store = Store(tmp_path / "db")
    load(path, store)
    return store, derive_schema(SCHEMA)


def test_every_relation_variant_is_in_the_schema(loaded):
    _, schema = loaded
    pairs = {tuple(sorted(e.roles.values())) for e in schema.edges.values()}
    assert ("country", "mountain") in pairs
    assert ("country", "lake") in pairs
    assert ("continent", "country") in pairs


def test_all_edges_load(loaded):
    store, _ = loaded
    assert len(store.edge_index) == 4


def test_edge_roles_match_the_declared_schema(loaded):
    """Every loaded edge must use the role names its edge type declares,
    otherwise following it raises KeyError at query time."""
    store, schema = loaded
    for edge in store.edge_index.values():
        assert edge.type in schema.edges, f"{edge.type} not in schema"
        assert set(edge.roles) == set(schema.edges[edge.type].roles), edge.type


def test_can_query_each_variant(loaded):
    store, schema = loaded

    def edge_for(subj, obj):
        for name, e in schema.edges.items():
            if set(e.roles.values()) == {subj, obj}:
                return name
        raise AssertionError(f"no edge type for {subj}->{obj}")

    mountain_country = edge_for("mountain", "country")
    rows = execute_rows(
        verify(
            parse(
                f'find mountain where name = "K2" as m\n'
                f"follow m {mountain_country} country as c\n"
                "return c.name"
            ),
            schema,
        ),
        store,
        schema,
    )
    assert rows == [["Pakistan"]]

    country_continent = edge_for("country", "continent")
    rows = execute_rows(
        verify(
            parse(
                f'find country where name = "Pakistan" as c\n'
                f"follow c {country_continent} continent as k\n"
                "return k.name"
            ),
            schema,
        ),
        store,
        schema,
    )
    assert rows == [["Asia"]]


def test_unique_label_keeps_its_plain_name(loaded):
    _, schema = loaded
    assert "flowsInto" in schema.edges

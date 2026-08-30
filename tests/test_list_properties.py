"""Multi-valued properties.

Wikidata-derived graphs carry list-valued properties (several
citizenships, several owners). Flattening them to one joined string made
them unreadable as values and unmatchable against anything that expects
the list back.
"""

import json

from eval.load_graph import derive_schema, load
from theorem.engine.executor import execute_rows
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.verifier import verify

SCHEMA = {
    "name": "mini",
    "entities": [
        {
            "label": "Player",
            "properties": {"country_of_citizenship": "list[str]", "height_cm": "float"},
        }
    ],
    "relations": [],
}

KG = {
    "schema": SCHEMA,
    "entities": [
        {
            "eid": "Player#1",
            "label": "Player",
            "name": "Ana",
            "properties": {
                "country_of_citizenship": ["Japan", "Brazil"],
                "height_cm": 180.0,
            },
        },
        {
            "eid": "Player#2",
            "label": "Player",
            "name": "Bo",
            "properties": {"country_of_citizenship": ["Japan"], "height_cm": 190.0},
        },
    ],
    "relations": [],
}


def _load(tmp_path):
    path = tmp_path / "kg.json"
    path.write_text(json.dumps(KG))
    store = Store(tmp_path / "db")
    load(path, store)
    return store, derive_schema(SCHEMA)


def run(text, store, schema):
    return execute_rows(verify(parse(text), schema), store, schema)


def test_list_property_returns_the_list(tmp_path):
    store, schema = _load(tmp_path)
    rows = run(
        'find player where name = "Ana" as p\nreturn p.country_of_citizenship',
        store,
        schema,
    )
    assert rows == [[["Japan", "Brazil"]]]


def test_equality_matches_any_member(tmp_path):
    """A player "is" Japanese if Japan is one of their citizenships."""
    store, schema = _load(tmp_path)
    rows = run(
        'find player where country_of_citizenship = "Japan" as p\nreturn p.name',
        store,
        schema,
    )
    assert sorted(rows) == [["Ana"], ["Bo"]]


def test_equality_does_not_match_a_non_member(tmp_path):
    store, schema = _load(tmp_path)
    rows = run(
        'find player where country_of_citizenship = "Peru" as p\nreturn p.name',
        store,
        schema,
    )
    assert rows == []


def test_contains_matches_within_a_member(tmp_path):
    store, schema = _load(tmp_path)
    rows = run(
        'find player where country_of_citizenship contains "Braz" as p\nreturn p.name',
        store,
        schema,
    )
    assert rows == [["Ana"]]


def test_not_equal_excludes_members(tmp_path):
    store, schema = _load(tmp_path)
    rows = run(
        'find player where country_of_citizenship != "Brazil" as p\nreturn p.name',
        store,
        schema,
    )
    assert rows == [["Bo"]]


def test_scalar_properties_are_unaffected(tmp_path):
    store, schema = _load(tmp_path)
    rows = run("find player where height_cm > 185 as p\nreturn p.name", store, schema)
    assert rows == [["Bo"]]

"""Properties that belong to the relationship, not to either end.

"Which teams did this player play for in 1983" is a question about the
edge: when the spell started and when it ended. Without edge properties
the question cannot be asked at all, and incomplete data (an ongoing
spell with no end year) has to be expressible too.
"""

import json

import pytest

from eval.load_graph import derive_schema, load
from theorem.engine.executor import execute_rows
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.verifier import VerifyError, verify

SCHEMA = {
    "name": "mini",
    "entities": [
        {"label": "Player", "properties": {}},
        {"label": "Team", "properties": {}},
    ],
    "relations": [
        {
            "label": "playsFor",
            "subj_label": "Player",
            "obj_label": "Team",
            "properties": {"start_year": "int", "end_year": "int"},
        }
    ],
}

KG = {
    "schema": SCHEMA,
    "entities": [
        {"eid": "Player#1", "label": "Player", "name": "Reid", "properties": {}},
        {"eid": "Team#1", "label": "Team", "name": "Rockets", "properties": {}},
        {"eid": "Team#2", "label": "Team", "name": "Hornets", "properties": {}},
        {"eid": "Team#3", "label": "Team", "name": "Spurs", "properties": {}},
    ],
    "relations": [
        {"rid": "0", "label": "playsFor", "subj_id": "Player#1", "obj_id": "Team#1",
         "properties": {"start_year": 1982, "end_year": 1988}},
        {"rid": "1", "label": "playsFor", "subj_id": "Player#1", "obj_id": "Team#2",
         "properties": {"start_year": 1988, "end_year": 1990}},
        {"rid": "2", "label": "playsFor", "subj_id": "Player#1", "obj_id": "Team#3",
         "properties": {"start_year": 1991}},  # ongoing: no end year
    ],
}


@pytest.fixture
def loaded(tmp_path):
    path = tmp_path / "kg.json"
    path.write_text(json.dumps(KG))
    store = Store(tmp_path / "db")
    load(path, store)
    return store, derive_schema(SCHEMA)


def run(text, loaded):
    store, schema = loaded
    return execute_rows(verify(parse(text), schema), store, schema)


def test_edge_properties_are_loaded(loaded):
    store, _ = loaded
    years = sorted(
        e.props.get("start_year") for e in store.edge_index.values()
    )
    assert years == [1982, 1988, 1991]


def test_filter_on_edge_property(loaded):
    rows = run(
        'find player where name = "Reid" as p\n'
        "follow p playsFor team as t where via.start_year <= 1983\n"
        "return t.name",
        loaded,
    )
    assert rows == [["Rockets"]]


def test_edge_and_node_conditions_combine(loaded):
    rows = run(
        'find player where name = "Reid" as p\n'
        "follow p playsFor team as t where via.start_year <= 1983 "
        'and via.end_year >= 1983\n'
        "return t.name",
        loaded,
    )
    assert rows == [["Rockets"]]


def test_missing_edge_property_is_none(loaded):
    """The ongoing spell has no end year, and asking for the ones that
    have ended must not include it."""
    rows = run(
        'find player where name = "Reid" as p\n'
        "follow p playsFor team as t where via.end_year != none\n"
        "return t.name order by t.name",
        loaded,
    )
    assert rows == [["Hornets"], ["Rockets"]]


def test_none_matches_only_the_missing_one(loaded):
    rows = run(
        'find player where name = "Reid" as p\n'
        "follow p playsFor team as t where via.end_year = none\n"
        "return t.name",
        loaded,
    )
    assert rows == [["Spurs"]]


def test_a_year_inside_an_ongoing_spell(loaded):
    """1995: the Spurs spell started in 1991 and has not ended."""
    rows = run(
        'find player where name = "Reid" as p\n'
        "follow p playsFor team as t where via.start_year <= 1995 "
        "and via.end_year = none\n"
        "return t.name",
        loaded,
    )
    assert rows == [["Spurs"]]


def test_unknown_edge_property_is_rejected(loaded):
    _, schema = loaded
    with pytest.raises(VerifyError):
        verify(
            parse(
                'find player as p\nfollow p playsFor team as t where via.bogus = 1\n'
                "return t.name"
            ),
            schema,
        )

import json

from eval.load_graph import derive_schema, load, role_names
from theorem.engine.executor import ReadContext, execute_read
from theorem.engine.storage import Store
from theorem.parser import parse
from theorem.verifier import verify

MINI_SCHEMA = {
    "name": "mini",
    "entities": [
        {
            "label": "Team",
            "properties": {"inception_year": "int", "owners": "list[str]"},
        },
        {
            "label": "Player",
            "properties": {"height_cm": "float", "date_of_birth": "date"},
        },
        {"label": "Person", "properties": {}},
    ],
    "relations": [
        {
            "label": "playsFor",
            "subj_label": "Player",
            "obj_label": "Team",
            "properties": {"start_year": "int"},
        },
        {
            "label": "mentors",
            "subj_label": "Person",
            "obj_label": "Person",
            "properties": {},
        },
    ],
}

MINI_KG = {
    "schema": MINI_SCHEMA,
    "entities": [
        {
            "eid": "Team#Q1",
            "label": "Team",
            "name": "Lakers",
            "properties": {"inception_year": 1946, "owners": ["Jeanie Buss"]},
        },
        {
            "eid": "Player#Q2",
            "label": "Player",
            "name": "LeBron James",
            "properties": {"height_cm": 206.0, "date_of_birth": "1984-12-30"},
        },
        {
            "eid": "Player#Q3",
            "label": "Player",
            "name": "Nikola Jokic",
            "properties": {"height_cm": 211.0, "date_of_birth": None},
        },
    ],
    "relations": [
        {
            "rid": "0",
            "label": "playsFor",
            "subj_id": "Player#Q2",
            "obj_id": "Team#Q1",
            "properties": {"start_year": 2018},
        },
        {
            "rid": "1",
            "label": "playsFor",
            "subj_id": "Player#QMISSING",
            "obj_id": "Team#Q1",
            "properties": {},
        },
    ],
}


def test_derive_schema():
    schema = derive_schema(MINI_SCHEMA)
    assert set(schema.classes) == {"team", "player", "person"}
    assert schema.classes["team"].props["name"] == "str"
    assert schema.classes["team"].props["inception_year"] == "int"
    assert schema.classes["team"].props["owners"] == "str"  # lists join to str
    assert schema.classes["player"].props["date_of_birth"] == "str"
    assert schema.edges["playsFor"].roles == {"player": "player", "team": "team"}
    assert schema.edges["mentors"].roles == {
        "subj": "subj",
        "obj": "obj",
    } or schema.edges["mentors"].roles == {"subj": "person", "obj": "person"}


def test_role_names_same_label():
    assert role_names("Person", "Person") == ("subj", "obj")


def test_load_and_query(tmp_path):
    kg_path = tmp_path / "mini.json"
    kg_path.write_text(json.dumps(MINI_KG))
    store = Store(tmp_path / "db")
    schema = derive_schema(MINI_SCHEMA)
    id_map = load(kg_path, store)
    assert len(id_map) == 3
    assert len(store.edge_index) == 1  # dangling relation skipped

    out = execute_read(
        verify(
            parse(
                'find player where name = "LeBron James" as p\n'
                "follow p playsFor team as t\nreturn t.name"
            ),
            schema,
        ),
        store,
        schema,
        ReadContext(),
    )
    assert "Lakers" in out

    # null property dropped, list property joined
    out = execute_read(
        verify(
            parse('find team where owners contains "Buss" as t\nreturn t.name'), schema
        ),
        store,
        schema,
        ReadContext(),
    )
    assert "Lakers" in out

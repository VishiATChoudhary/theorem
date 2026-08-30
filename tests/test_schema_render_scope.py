"""The schema an agent is shown should be the schema that has data.

theorem defines built-in ingestion classes (document, chunk, media,
piece) on every schema. On a graph that holds none of them they are
tokens in every prompt and an invitation to query something empty.
"""

from theorem.engine.storage import Store
from theorem.schema import ClassDef, EdgeDef, Schema


def _schema():
    s = Schema()
    s.classes["team"] = ClassDef(name="team", props={"name": "str"})
    s.classes["player"] = ClassDef(name="player", props={"name": "str"})
    s.edges["playsFor"] = EdgeDef(
        name="playsFor", roles={"player": "player", "team": "team"}
    )
    return s


def test_default_render_is_unchanged(tmp_path):
    """Nothing passed, nothing hidden: a write workflow still needs to see
    classes it has not populated yet."""
    out = _schema().render()
    assert "document" in out and "team" in out


def test_render_against_a_store_hides_empty_classes(tmp_path):
    schema = _schema()
    store = Store(tmp_path / "db")
    nid = store.next_id("team")
    store.apply(
        {"op": "put_node", "id": nid, "cls": "team", "props": {"name": "Bulls"}}
    )
    out = schema.render(store)
    assert "team" in out
    assert "document" not in out
    assert "chunk" not in out
    assert "player" not in out  # declared but empty


def test_edges_to_hidden_classes_are_hidden_too(tmp_path):
    schema = _schema()
    store = Store(tmp_path / "db")
    nid = store.next_id("team")
    store.apply(
        {"op": "put_node", "id": nid, "cls": "team", "props": {"name": "Bulls"}}
    )
    out = schema.render(store)
    # playsFor needs a player, and there are none, so showing it would
    # offer a traversal that cannot go anywhere.
    assert "playsFor" not in out
    assert "part_of" not in out


def test_edges_between_populated_classes_survive(tmp_path):
    schema = _schema()
    store = Store(tmp_path / "db")
    for cls, name in (("team", "Bulls"), ("player", "Jordan")):
        nid = store.next_id(cls)
        store.apply(
            {"op": "put_node", "id": nid, "cls": cls, "props": {"name": name}}
        )
    out = schema.render(store)
    assert "playsFor" in out and "team" in out and "player" in out


def test_render_against_an_empty_store_hides_everything(tmp_path):
    out = _schema().render(Store(tmp_path / "db"))
    assert "classes:" in out
    assert "team" not in out

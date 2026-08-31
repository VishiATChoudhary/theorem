"""A reader that can catch up with a writer.

A store reads its directory at open, so a second process holding it open
for reads answers from the graph as it was when it opened. For a
dashboard or an API server beside a writer, that is a wrong answer with
no symptom.
"""

from theorem import Schema, Session
from theorem.engine.storage import Store


def put(store, name):
    nid = store.next_id("supplier")
    store.apply(
        {"op": "put_node", "id": nid, "cls": "supplier", "props": {"name": name}}
    )
    return nid


def test_a_reader_sees_nothing_new_until_it_refreshes(tmp_path):
    writer = Store(tmp_path)
    put(writer, "VoltaChem")
    reader = Store(tmp_path, lock=False)
    assert len(reader.nodes) == 1

    put(writer, "Ionix")
    assert len(reader.nodes) == 1  # the read is of the graph it opened
    assert reader.refresh() == 1
    assert len(reader.nodes) == 2
    writer.close()
    reader.close()


def test_refreshing_with_nothing_new_is_a_no_op(tmp_path):
    writer = Store(tmp_path)
    put(writer, "VoltaChem")
    reader = Store(tmp_path, lock=False)
    assert reader.refresh() == 0
    assert reader.position == writer.position
    writer.close()
    reader.close()


def test_a_reader_survives_the_writer_compacting(tmp_path):
    """A snapshot truncates the log out from under the reader. Selecting
    records by position rather than by byte offset makes that the same
    case as any other: the run file is newer, so rebuild from it."""
    writer = Store(tmp_path, snapshot_every=5)
    for i in range(3):
        put(writer, f"s{i}")
    reader = Store(tmp_path, lock=False)
    assert len(reader.nodes) == 3

    for i in range(3, 30):
        put(writer, f"s{i}")
    assert writer.wal_len() < 30  # it compacted

    reader.refresh()
    assert len(reader.nodes) == 30
    assert reader.position == writer.position
    writer.close()
    reader.close()


def test_a_reader_ignores_a_half_written_record(tmp_path):
    """A writer mid-append leaves a line with no newline on it."""
    writer = Store(tmp_path)
    put(writer, "VoltaChem")
    reader = Store(tmp_path, lock=False)
    with writer.wal_path.open("a", encoding="utf-8") as f:
        f.write('{"op": "put_node", "id": "#s-9", "cls": "supp')
    assert reader.refresh() == 0
    assert len(reader.nodes) == 1
    writer.close()
    reader.close()


def test_a_session_can_follow_one(tmp_path):
    db = tmp_path / "db"
    with Session(db, Schema.supply_chain()) as writer:
        writer.run('assert supplier {name: "VoltaChem", country: "DE"} as v')
        reader = Session(db, Schema.supply_chain(), lock=False)
        assert reader.rows("find supplier as s\nreturn s.name") == [["VoltaChem"]]

        writer.run('assert supplier {name: "Ionix", country: "KR"} as i')
        reader.store.refresh()
        assert reader.rows("find supplier as s\nreturn s.name order by s.name") == [
            ["Ionix"],
            ["VoltaChem"],
        ]
        reader.close()


def test_a_readers_index_catches_up_too(tmp_path):
    """A reader that built an index and then replayed new records must not
    answer from the index it had before them."""
    from theorem.engine.executor import execute_rows
    from theorem.parser import parse
    from theorem.schema import ClassDef, Schema
    from theorem.verifier import verify

    schema = Schema()
    schema.classes["supplier"] = ClassDef("supplier", {"name": "str", "country": "str"})
    query = 'find supplier where country = "JP" as s\nreturn s.name'

    writer = Store(tmp_path)
    writer.bulk(
        [
            {
                "op": "put_node",
                "id": f"#s-{i}",
                "cls": "supplier",
                "props": {"name": f"S{i}", "country": "DE"},
            }
            for i in range(1, 6001)
        ]
    )
    reader = Store(tmp_path, lock=False)
    assert execute_rows(verify(parse(query), schema), reader, schema) == []
    assert reader.indexed_props  # the index is built and says nobody is in JP

    writer.apply(
        {
            "op": "put_node",
            "id": "#s-9999",
            "cls": "supplier",
            "props": {"name": "Ionix", "country": "JP"},
        }
    )
    writer.apply({"op": "patch_node", "id": "#s-1", "props": {"country": "JP"}})
    reader.refresh()

    found = sorted(
        r[0] for r in execute_rows(verify(parse(query), schema), reader, schema)
    )
    assert found == ["Ionix", "S1"]
    writer.close()
    reader.close()

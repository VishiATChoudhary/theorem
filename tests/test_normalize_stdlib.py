import pytest

from theorem.ingest.normalize import IngestError, normalize


def test_markdown_passthrough():
    env = normalize(b"# T\n\nbody text", "n.md")
    assert env.body.startswith("# T")
    assert env.meta["format"] == "markdown"


def test_csv_becomes_table_not_body():
    env = normalize(b"name,cost\nbolt,1.0\n", "parts.csv")
    assert env.body == ""
    assert env.tables[0].rows == [{"name": "bolt", "cost": "1.0"}]
    assert env.tables[0].name == "parts"


def test_homogeneous_json_array_becomes_table():
    env = normalize(b'[{"a": "1"}, {"a": "2"}]', "d.json")
    assert len(env.tables[0].rows) == 2


def test_hetero_json_stays_body():
    env = normalize(b'{"a": {"b": 1}}', "d.json")
    assert "```json" in env.body


def test_jsonl_becomes_table_with_union_columns():
    env = normalize(b'{"a": "1"}\n{"b": "2"}\n', "d.jsonl")
    assert set(env.tables[0].rows[1].keys()) == {"a", "b"}


def test_binary_rejected():
    with pytest.raises(IngestError):
        normalize(b"\x00\x01", "blob.bin")


def test_pdf_without_extra_names_the_extra():
    with pytest.raises(IngestError, match=r"theorem\[pdf\]"):
        normalize(b"%PDF-1.7", "d.pdf")

import sys

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


def test_pdf_without_extra_names_the_extra(monkeypatch):
    # Simulate pdfplumber being absent regardless of whether the pdf extra
    # happens to be installed in this environment: setting a module to None
    # in sys.modules makes `import pdfplumber` raise ImportError.
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    with pytest.raises(IngestError, match=r"theoremql\[pdf\]"):
        normalize(b"%PDF-1.7", "d.pdf")


def test_json_overlapping_keys_union():
    env = normalize(b'[{"a": "1", "b": "2"}, {"a": "3"}]', "d.json")
    assert env.body == ""
    assert len(env.tables) == 1
    assert set(env.tables[0].rows[0].keys()) == {"a", "b"}
    assert set(env.tables[0].rows[1].keys()) == {"a", "b"}
    assert env.tables[0].rows[0] == {"a": "1", "b": "2"}
    assert env.tables[0].rows[1] == {"a": "3", "b": ""}

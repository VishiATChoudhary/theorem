import pytest

from theorem.ingest.chunk import split
from theorem.ingest.normalize import normalize
from theorem.ingest.stage import stage
from theorem.schema import Schema
from theorem.session import Session


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def test_split_respects_headings_and_cap():
    body = "# A\n" + ("word " * 700) + "\n# B\nshort"
    chunks = split(body, [])
    assert len(chunks) >= 3  # A splits by cap, B separate
    from theorem.engine.executor import count_tokens

    assert all(count_tokens(t) <= 600 for t, _ in chunks)


def test_stage_document_and_chunks(sess):
    raw = b"# Title\n\nHello graph world.\n\n# Part two\n\nMore text."
    env = normalize(raw, "notes.md")
    r = stage(sess, env, "notes.md", raw)
    assert not r.existing and r.chunks >= 2
    out = sess.run("find chunk as c\nfollow c part_of whole as d\nreturn d.title")
    assert "notes.md" in out


def test_stage_sha_dedup(sess):
    raw = b"# Same\ncontent"
    env = normalize(raw, "a.md")
    r1 = stage(sess, env, "a.md", raw)
    r2 = stage(sess, env, "a.md", raw)
    assert r2.existing and r2.doc_id == r1.doc_id


def test_staged_table_is_refinable(sess):
    raw = b"name,unit_cost\nbolt,1.0\n"
    env = normalize(raw, "parts.csv")
    r = stage(sess, env, "parts.csv", raw)
    out = sess.run(
        f"refine {r.doc_table_ids[0]} into part with "
        f'{{name: col "name", unit_cost: col "unit_cost"}} as np'
    )
    assert "refined" in out

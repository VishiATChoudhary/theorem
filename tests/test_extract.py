import pytest

from theorem.ingest.extract import extract
from theorem.ingest.normalize import normalize
from theorem.ingest.stage import stage
from theorem.schema import Schema
from theorem.session import Session


class ScriptedRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return self.outputs.pop(0)


@pytest.fixture
def staged(tmp_path):
    sess = Session(tmp_path / "db", Schema.supply_chain())
    raw = b"VoltaChem is a supplier based in Germany."
    r = stage(sess, normalize(raw, "note.md"), "note.md", raw)
    return sess, r.doc_id


def test_extract_happy_path(staged):
    sess, doc = staged
    good = (
        'assert supplier {name: "VoltaChem", country: "DE"} source doc:note.md#p0 as s1'
    )
    r = extract(sess, doc, ScriptedRunner([good]))
    assert r.chunks_done == 1 and r.chunks_failed == 0
    out = sess.run("find supplier as s\nreturn s.name")
    assert "VoltaChem" in out


def test_extract_repair_retry(staged):
    sess, doc = staged
    bad = 'assert supplier {name: "VoltaChem", contry: "DE"} as s1'
    good = 'assert supplier {name: "VoltaChem", country: "DE"} as s1'
    runner = ScriptedRunner([bad, good])
    r = extract(sess, doc, runner)
    assert r.chunks_done == 1
    assert "contry" in runner.prompts[1]  # error fed back


def test_extract_failure_flags_document(staged):
    sess, doc = staged
    bad = "total nonsense ((("
    r = extract(sess, doc, ScriptedRunner([bad, bad]))
    assert r.chunks_failed == 1
    out = sess.run("find document as d\nreturn d.query_traffic, d.health")
    assert "query" in out  # flag landed -> health.query nonzero renders


def test_extract_uses_stored_focus(staged):
    sess, doc = staged
    sess.store.apply(
        {
            "op": "patch_node",
            "id": doc,
            "props": {"_focus": "Prioritize launch dates. Ignore boilerplate."},
        }
    )
    good = (
        'assert supplier {name: "VoltaChem", country: "DE"} source doc:note.md#p0 as s1'
    )
    runner = ScriptedRunner([good])
    extract(sess, doc, runner)
    assert "Prioritize launch dates." in runner.prompts[0]


def test_extract_budget_stops(staged):
    sess, doc = staged
    r = extract(sess, doc, ScriptedRunner([]), budget=1)
    assert r.stopped_early and r.chunks_done == 0

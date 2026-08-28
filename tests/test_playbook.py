import pytest

from theorem.ingest.playbook import compile_playbook
from theorem.schema import Schema
from theorem.session import Session

RESPONSE = """```theorem
derive class competitor from entity with {hq_country: str} quota 50
derive edge competes_with(us: competitor, them: competitor)
```
```summary
competitor: "Companies that compete with us" (quote). competes_with: rivalry link.
```
```focus
Prioritize launch dates. Ignore boilerplate.
```"""


class One:
    def __init__(self, out):
        self.out = out

    def run(self, prompt):
        return self.out


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def _pb(tmp_path):
    p = tmp_path / "pb.md"
    p.write_text("# Competitors\nWe track companies that compete with us.")
    return p


def test_guided_applies_on_confirm(sess, tmp_path):
    compile_playbook(sess, _pb(tmp_path), One(RESPONSE), confirm=lambda s: True)
    assert "competitor" in sess.schema.classes
    assert "competes_with" in sess.schema.edges
    assert sess.schema.classes["competitor"].quota == 50


def test_guided_abort_on_reject(sess, tmp_path):
    compile_playbook(sess, _pb(tmp_path), One(RESPONSE), confirm=lambda s: False)
    assert "competitor" not in sess.schema.classes


def test_unhinged_skips_confirm(sess, tmp_path):
    called = []
    compile_playbook(
        sess,
        _pb(tmp_path),
        One(RESPONSE),
        unhinged=True,
        confirm=lambda s: called.append(1) or True,
    )
    assert "competitor" in sess.schema.classes and not called


def test_recompile_deprecates_removed(sess, tmp_path):
    compile_playbook(sess, _pb(tmp_path), One(RESPONSE), confirm=lambda s: True)
    without_edgeclass = (
        RESPONSE.replace(
            "derive class competitor from entity with {hq_country: str} quota 50\n", ""
        )
        .replace("derive edge competes_with", "derive edge rivals_with")
        .replace("us: competitor, them: competitor", "us: supplier, them: supplier")
    )
    compile_playbook(
        sess, _pb(tmp_path), One(without_edgeclass), confirm=lambda s: True
    )
    assert sess.schema.classes["competitor"].status == "deprecated"


def test_focus_stored(sess, tmp_path):
    r = compile_playbook(sess, _pb(tmp_path), One(RESPONSE), confirm=lambda s: True)
    node = sess.store.nodes[r.doc_id]
    assert "launch dates" in node.props["_focus"].lower()

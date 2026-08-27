"""Regression tests for the launch edge-case review findings.

Each test corresponds to a numbered finding from the pre-launch review;
tests were written first, fixes after.
"""

import json

import pytest

from theorem.engine.storage import Store
from theorem.parser import ParseError, parse
from theorem.schema import Schema
from theorem.session import Session


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


# ---- #2: snapshot / WAL double-apply on crash between run write and truncate


def test_snapshot_crash_before_truncate_does_not_double_apply(tmp_path):
    store = Store(tmp_path / "db")
    nid = store.next_id("product")
    store.apply({"op": "put_node", "id": nid, "cls": "product", "props": {"name": "p"}})
    store.apply({"op": "lineage", "kind": "merge", "survivor": nid, "absorbed": "x"})
    wal_before = store.wal_path.read_text()
    store.snapshot()
    # simulate a crash after the run file landed but before WAL truncation
    store.wal_path.write_text(wal_before)
    reopened = Store(tmp_path / "db")
    merges = [r for r in reopened.lineage if r.get("kind") == "merge"]
    assert len(merges) == 1


def test_wal_records_carry_position(tmp_path):
    store = Store(tmp_path / "db")
    nid = store.next_id("product")
    store.apply({"op": "put_node", "id": nid, "cls": "product", "props": {}})
    rec = json.loads(store.wal_path.read_text().splitlines()[0])
    assert rec["_pos"] == 1


# ---- #3: derived classes must survive a restart


def test_derived_class_survives_restart(tmp_path):
    db = tmp_path / "db"
    s1 = Session(db, Schema.supply_chain())
    out = s1.run("derive class gadget from product with {warranty_years: int}")
    assert "provisional" in out
    out = s1.run('assert gadget {name: "Widget", warranty_years: 2} as w')
    assert "created gadget" in out

    s2 = Session(db, Schema.supply_chain())
    out = s2.run("find gadget as g\nreturn g.name")
    assert "Widget" in out
    out = s2.run('assert gadget {name: "Widget2", warranty_years: 3} as w2')
    assert "created gadget" in out


# ---- #5: session never leaks a raw exception


def test_session_internal_errors_become_messages(sess, monkeypatch):
    import theorem.session as session_mod

    def boom(*a, **k):
        raise ValueError("kaboom")

    monkeypatch.setattr(session_mod, "execute_read", boom)
    out = sess.run("find product as p\nreturn p.name")
    assert isinstance(out, str)
    assert "internal error" in out


# ---- #6: aggregate columns are verified


def test_aggregate_unknown_property_rejected(sess):
    out = sess.run("find product as p\nsum p.totaly_bogus as x\nreturn x")
    assert "nothing was executed" in out
    assert "totaly_bogus" in out


def test_aggregate_sum_on_string_property_rejected(sess):
    out = sess.run("find supplier as s\nsum s.name as x\nreturn x")
    assert "nothing was executed" in out


def test_aggregate_unknown_group_member_rejected(sess):
    out = sess.run(
        "find product as p\nfollow p uses component as parts\n"
        "group by p as g\ncount distinct g.bogus as n\nreturn n"
    )
    assert "nothing was executed" in out


def test_valid_aggregates_still_pass(sess):
    sess.run('assert product {name: "A", launch_year: 2025} as a')
    out = sess.run("find product as p\nsum p.launch_year as total\nreturn total")
    assert "2025" in out


# ---- #8: negative budget / limit are parse errors


def test_negative_budget_rejected():
    with pytest.raises(ParseError):
        parse("find product as p\nreturn p.name budget -100 tokens")


def test_negative_limit_rejected():
    with pytest.raises(ParseError):
        parse("find product as p\nreturn p.name limit -5")


def test_zero_budget_rejected():
    with pytest.raises(ParseError):
        parse("find product as p\nreturn p.name budget 0 tokens")


# ---- #9: assert literal types checked against schema


def test_assert_wrong_literal_type_rejected(sess):
    out = sess.run('assert product {name: "P", launch_year: "not-a-year"} as p')
    assert "nothing was executed" in out
    assert "launch_year" in out


def test_assert_int_ok_for_float_prop(sess):
    out = sess.run('assert part {name: "bolt", unit_cost: 2} as b')
    assert "created part" in out


def test_assert_bool_not_accepted_as_int(sess):
    out = sess.run('assert product {name: "P", launch_year: true} as p')
    assert "nothing was executed" in out


# ---- #15: replay skips records referencing missing nodes instead of crashing


def test_replay_tolerates_dangling_records(tmp_path):
    store = Store(tmp_path / "db")
    nid = store.next_id("product")
    store.apply({"op": "put_node", "id": nid, "cls": "product", "props": {}})
    with store.wal_path.open("a") as f:
        f.write(json.dumps({"op": "retire", "id": "#p-999", "reason": "x"}) + "\n")
        f.write(json.dumps({"op": "traffic", "id": "#p-999"}) + "\n")
    reopened = Store(tmp_path / "db")  # must not raise
    assert nid in reopened.nodes


# ---- CJK strings must not collapse to equal under folding


def test_fold_preserves_cjk(sess):
    sess.run('assert supplier {name: "北京", country: "CN"} as a')
    sess.run('assert supplier {name: "東京", country: "JP"} as b')
    out = sess.run('find supplier where name = "北京" as s\nreturn s.name')
    assert "results: 1 of 1" in out


# ---- interior WAL corruption must not delete a valid suffix


def test_interior_wal_corruption_preserves_suffix(tmp_path):
    store = Store(tmp_path / "db")
    for i in range(2):
        nid = store.next_id("product")
        store.apply(
            {"op": "put_node", "id": nid, "cls": "product", "props": {"name": f"p{i}"}}
        )
    lines = store.wal_path.read_text().splitlines()
    store.wal_path.write_text(lines[0] + "\nnot-json\n" + lines[1] + "\n")
    with pytest.raises(Exception) as exc:
        Store(tmp_path / "db")
    assert "corrupt" in str(exc.value).lower()
    # the valid suffix must still be on disk, not truncated away
    assert lines[1] in store.wal_path.read_text()


def test_non_utf8_wal_tail_recovers(tmp_path):
    store = Store(tmp_path / "db")
    nid = store.next_id("product")
    store.apply({"op": "put_node", "id": nid, "cls": "product", "props": {}})
    with store.wal_path.open("ab") as f:
        f.write(b"\xff\n")
    # an unreadable tail line is a torn write: recover the prefix, no crash
    reopened = Store(tmp_path / "db")
    assert nid in reopened.nodes
    assert b"\xff" not in store.wal_path.read_bytes()


# ---- distinct x, x must be rejected, not brick snapshots


def test_self_distinct_rejected(sess):
    sess.run('assert supplier {name: "Solo", country: "DE"} as s')
    out = sess.run('distinct s, s reason "same"')
    assert "error" in out
    # store must still snapshot cleanly
    sess.store.snapshot()


# ---- an empty seeded table must not be resurrected by a later find


def test_empty_table_not_resurrected(sess):
    sess.run('assert part {name: "bolt", unit_cost: 1.0} as b')
    out = sess.run("find product as none\nfind part as p\nreturn p.name")
    assert "results: 0 of 0" in out


# ---- attach references must not escape the attachments directory


def test_attachment_path_traversal_rejected(sess, tmp_path):
    secret = tmp_path / "secret.csv"
    secret.write_text("name\nleak\n")
    out = sess.run(
        f'assert table_blob {{title: "x", payload: attach:../../{secret.stem}}} as b'
    )
    assert "error" in out
    out2 = sess.run(
        f'assert table_blob {{title: "x", payload: attach:{secret.parent}/{secret.stem}}} as b2'
    )
    assert "error" in out2


# ---- derive then use in the same program must verify


def test_derive_then_assert_same_program(sess):
    out = sess.run(
        "derive class gadget from product with {warranty_years: int}\n"
        'assert gadget {name: "W", warranty_years: 1} as w'
    )
    assert "created gadget" in out


def test_duplicate_derive_same_program_rejected(sess):
    out = sess.run(
        "derive class gadget from product with {x: int}\n"
        "derive class gadget from product with {y: int}"
    )
    assert "nothing was executed" in out


# ---- parser robustness: bad aggregate verb shape, huge integers


def test_aggregate_bare_verb_is_parse_error():
    with pytest.raises(ParseError):
        parse("aggregate p as n")


def test_huge_integer_literal_is_parse_error():
    with pytest.raises(ParseError):
        parse("find product as p\nreturn p.name limit " + "9" * 4301)


# ---- #16a: derived class names must be lowercase identifiers, not reserved


def test_derive_uppercase_class_name_rejected(sess):
    out = sess.run("derive class Gadget from product with {x: int}")
    assert "nothing was executed" in out


def test_derive_reserved_name_rejected(sess):
    out = sess.run("derive class nodes from product with {x: int}")
    assert "nothing was executed" in out

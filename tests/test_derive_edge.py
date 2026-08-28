import pytest

from theorem.parser import ParseError, parse
from theorem.schema import Schema
from theorem.session import Session


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def test_derive_edge_creates_usable_edge(sess):
    out = sess.run("derive edge acquired(buyer: supplier, target: supplier)")
    assert "receipt" in out and "acquired" in out
    sess.run('assert supplier {name: "A", country: "DE"} as a')
    sess.run('assert supplier {name: "B", country: "FR"} as b')
    out = sess.run("assert edge acquired(buyer: a, target: b)")
    assert "created edge acquired" in out


def test_derive_edge_unknown_class_rejected(sess):
    out = sess.run("derive edge x(a: nonexistent, b: supplier)")
    assert "nothing was executed" in out


def test_derive_edge_duplicate_rejected(sess):
    sess.run("derive edge acquired(buyer: supplier, target: supplier)")
    out = sess.run("derive edge acquired(buyer: supplier, target: supplier)")
    assert "nothing was executed" in out


def test_derive_edge_survives_restart(tmp_path):
    db = tmp_path / "db"
    s1 = Session(db, Schema.supply_chain())
    s1.run("derive edge acquired(buyer: supplier, target: supplier)")
    s2 = Session(db, Schema.supply_chain())
    assert "acquired" in s2.schema.edges


def test_derive_edge_needs_two_roles():
    with pytest.raises(ParseError):
        parse("derive edge x(a: part)")

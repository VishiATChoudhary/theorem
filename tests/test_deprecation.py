import pytest

from theorem.engine.writes import deprecate_class
from theorem.schema import Schema
from theorem.session import Session


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def test_deprecated_class_rejects_new_asserts(sess):
    sess.run("derive class widget from entity with {}")
    sess.run('assert widget {name: "a"} as a')
    deprecate_class(sess, "widget")
    out = sess.run('assert widget {name: "b"} as b')
    assert "deprecated" in out and "nothing was executed" in out
    # existing data stays queryable
    out = sess.run("find widget as w\nreturn w.name")
    assert "results: 1 of 1" in out


def test_deprecation_survives_restart(tmp_path):
    db = tmp_path / "db"
    s1 = Session(db, Schema.supply_chain())
    s1.run("derive class widget from entity with {}")
    deprecate_class(s1, "widget")
    s1.close()
    s2 = Session(db, Schema.supply_chain())
    assert s2.schema.classes["widget"].status == "deprecated"

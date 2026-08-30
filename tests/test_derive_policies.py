import pytest

from theorem.schema import Schema
from theorem.session import Session


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def test_quota_clause_enforced(sess):
    sess.run("derive class widget from entity with {} quota 2")
    sess.run('assert widget {name: "a"} as a')
    sess.run('assert widget {name: "b"} as b')
    out = sess.run('assert widget {name: "c"} as c')
    assert "quota" in out and "error" in out


def test_dedup_clause_sets_threshold(sess):
    sess.run("derive class brand from entity with {} dedup 0.99")
    sess.run('assert brand {name: "Volta Chemical"} as a')
    # 'Volta Chemical' vs 'Volta Chemicals' scores ~0.97: candidate under
    # the global 0.85, NOT under this class's 0.99
    out = sess.run('assert brand {name: "Volta Chemicals"} as b')
    assert "dup candidates" not in out


def test_policy_clauses_survive_restart(tmp_path):
    db = tmp_path / "db"
    s1 = Session(db, Schema.supply_chain())
    s1.run("derive class widget from entity with {} quota 2 dedup 0.95")
    s1.close()
    s2 = Session(db, Schema.supply_chain())
    assert s2.schema.classes["widget"].quota == 2
    assert s2.schema.classes["widget"].dedup_threshold == 0.95


def test_default_quota_unchanged(sess):
    sess.run("derive class widget from entity with {}")
    assert sess.schema.classes["widget"].quota == 500

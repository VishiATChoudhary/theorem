"""Every v0.2 verb, through the front door.

`or` and `keep` shipped unusable: they were missing from the session's
list of read statements, so any program containing one was routed to the
write path and rejected. The unit tests never caught it because they call
the executor directly, which is what the benchmark harness does too.
These go through `Session.run`, the way a user does.
"""

import pytest

from theorem import Schema, Session


@pytest.fixture
def sess(tmp_path):
    s = Session(tmp_path / "db", Schema.supply_chain())
    for name, cost in [("Anode", 0.4), ("Cathode", 0.6), ("Bolt", 0.1)]:
        s.run(f'assert part {{name: "{name}", unit_cost: {cost}}} as p')
    s.run('assert supplier {name: "VoltaChem", country: "DE"} as v')
    s.run('assert supplier {name: "Ionix", country: "KR"} as i')
    for part, sup in [
        ("Anode", "VoltaChem"),
        ("Cathode", "VoltaChem"),
        ("Bolt", "Ionix"),
    ]:
        s.run(
            f'find part where name = "{part}" as p\n'
            f'find supplier where name = "{sup}" as v\n'
            "assert edge supplied_by(item: p, source: v)"
        )
    yield s
    s.close()


def test_or_unions_two_branches(sess):
    assert sess.rows(
        'find part where name = "Anode" as p\n'
        "or\n"
        'find part where name = "Bolt" as p\n'
        "return p.name order by p.name"
    ) == [["Anode"], ["Bolt"]]


def test_keep_filters_after_the_count(sess):
    assert sess.rows(
        "find supplier as s\n"
        "follow s supplied_by item as p\n"
        "group by s as g\n"
        "count distinct g.p as n\n"
        "keep g where n > 1\n"
        "return s.name, n"
    ) == [["VoltaChem", 2]]


def test_or_none_keeps_the_row(sess):
    sess.run('assert part {name: "Orphan", unit_cost: 0.0} as o')
    rows = sess.rows(
        "find part as p\n"
        "follow p supplied_by source as s or none\n"
        "group by p as g\n"
        "count distinct g.s as n\n"
        "return p.name, n order by p.name"
    )
    assert ["Orphan", 0] in rows


def test_return_distinct_collapses_values(sess):
    assert sess.rows(
        "find supplier as s\nreturn distinct s.country order by s.country"
    ) == [
        ["DE"],
        ["KR"],
    ]


def test_upto_walks_through_the_session(sess):
    assert sess.rows(
        'find part where name = "Anode" as p\n'
        "follow p supplied_by source upto 1 as s\n"
        "return s.name"
    ) == [["VoltaChem"]]


def test_via_reads_the_edge(sess):
    sess.run(
        'find part where name = "Anode" as p\n'
        'find supplier where name = "Ionix" as v\n'
        "assert edge supplied_by(item: p, source: v)"
    )
    out = sess.run(
        "find part as p\n"
        "follow p supplied_by source as s where via.start_year = none\n"
        "return p.name"
    )
    assert "error" not in out.lower()


def test_name_reuse_joins(sess):
    """Both suppliers of the same part, and the same part."""
    sess.run(
        'find part where name = "Anode" as p\n'
        'find supplier where name = "Ionix" as v\n'
        "assert edge supplied_by(item: p, source: v)"
    )
    assert sess.rows(
        "find part as p\n"
        'follow p supplied_by source where country = "DE" as de\n'
        'follow p supplied_by source where country = "KR" as kr\n'
        "return p.name"
    ) == [["Anode"]]

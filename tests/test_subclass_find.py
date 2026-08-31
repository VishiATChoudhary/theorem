"""`derive class widget from part` means a widget is a part.

The rest of the system already agreed: a widget is accepted wherever a
role takes a part, and it inherits part's properties. `find part` did
not, so deriving a subclass quietly partitioned the data away from every
query written against the base. The shipped ingest pipeline hit it:
`chunk` and `media` derive from `piece`, so `find piece` answered nothing
on a store full of pieces.
"""

import pytest

from theorem import Schema, Session


@pytest.fixture
def sess(tmp_path):
    s = Session(tmp_path / "db", Schema.supply_chain())
    s.run("derive class widget from part with {sku: str}")
    s.run('assert part {name: "Anode", unit_cost: 0.4} as p')
    s.run('assert widget {name: "W1", sku: "S1", unit_cost: 1.0} as w')
    yield s
    s.close()


def test_a_base_class_finds_its_subclasses(sess):
    assert sess.rows("find part as p\nreturn p.name order by p.name") == [
        ["Anode"],
        ["W1"],
    ]


def test_a_subclass_still_finds_only_itself(sess):
    assert sess.rows("find widget as w\nreturn w.name") == [["W1"]]


def test_a_condition_applies_across_the_subclasses(sess):
    assert sess.rows("find part where unit_cost > 0.5 as p\nreturn p.name") == [["W1"]]


def test_a_name_lookup_spans_the_subclasses(sess):
    assert sess.rows('find part where name = "W1" as p\nreturn p.name') == [["W1"]]


def test_an_inherited_property_reads_on_a_subclass_instance(sess):
    assert sess.rows('find part where name = "W1" as p\nreturn p.unit_cost') == [[1.0]]


def test_counting_a_base_class_counts_the_subclasses(sess):
    assert sess.rows("find part as p\ncount distinct p as n\nreturn n") == [[2]]


def test_ingested_chunks_are_findable_as_pieces(tmp_path):
    """The bug as a user meets it: stage a document, then ask for pieces."""
    from theorem.ingest.normalize import normalize
    from theorem.ingest.stage import stage

    s = Session(tmp_path / "db", Schema.supply_chain())
    raw = b"# Title\n\nFirst paragraph.\n\nSecond paragraph.\n"
    stage(s, normalize(raw, "n.md"), "n.md", raw)

    chunks = s.rows("find chunk as c\nreturn c.id")
    assert chunks
    assert s.rows("find piece as p\nreturn p.id") == chunks
    s.close()


def test_an_unrelated_class_is_not_swept_in(tmp_path):
    s = Session(tmp_path / "db", Schema.supply_chain())
    s.run('assert part {name: "Anode", unit_cost: 0.4} as p')
    s.run('assert supplier {name: "VoltaChem", country: "DE"} as v')
    assert s.rows("find part as p\nreturn p.name") == [["Anode"]]
    s.close()


def test_a_deep_chain_is_followed(tmp_path):
    s = Session(tmp_path / "db", Schema.supply_chain())
    s.run("derive class widget from part with {sku: str}")
    s.run("derive class gadget from widget with {rev: int}")
    s.run('assert gadget {name: "G1", sku: "S", rev: 2, unit_cost: 1.0} as g')
    assert s.rows("find part as p\nreturn p.name") == [["G1"]]
    assert s.rows("find widget as w\nreturn w.name") == [["G1"]]
    s.close()

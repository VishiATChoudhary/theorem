"""The vendored CypherBench comparator must not fail one arm on a type.

Neo4j returns temporal values as driver objects. Dropping the branch that
converts them made every Cypher query returning a date raise and score
zero, which is a harness bug that reads as a language result.
"""

from eval.run_public import _compare_execution, rows_to_records, score, to_hashable


class _Date:
    """Stands in for neo4j.time.Date without needing the driver."""

    def __init__(self, s):
        self._s = s

    def iso_format(self):
        return self._s


def test_temporal_values_convert_rather_than_raise():
    assert to_hashable(_Date("1984-12-30")) == "1984-12-30"


def test_temporal_inside_a_list():
    assert to_hashable([_Date("2001-01-01"), _Date("1999-12-31")]) == (
        "1999-12-31",
        "2001-01-01",
    )


def test_a_date_row_matches_the_gold_string():
    """Gold answers store dates as ISO strings; a driver Date for the same
    day has to compare equal or the arm loses the question for nothing."""
    pred = [{"c0": to_hashable(_Date("1984-12-30"))}]
    gold = rows_to_records([["1984-12-30"]])
    assert _compare_execution(pred, gold, order_matters=False) == 1.0


def test_plain_scoring_still_works():
    assert score([["a"], ["b"]], "MATCH ... RETURN n", '[["b"], ["a"]]') == 1.0
    assert score([["a"]], "MATCH ... RETURN n", '[["b"]]') == 0.0

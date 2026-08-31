"""One spelling per program, restored at the level a cache can use.

The language accepts one redundant form: a condition may name the binding
its own statement creates. The parser normalizes it away, so canonicality
holds of the parse and not of the text. This renders the parse back to
text, which makes it hold of a string again.
"""

import pytest

from theorem.canonical import canonical
from theorem.parser import parse

PROGRAMS = [
    "find part as p\nreturn p.name",
    'find part where name = "Anode" as p\nreturn p.name',
    "find part as p\nfollow p supplied_by source as s\nreturn s.name",
    "find part as p\nfollow p supplied_by source as s or none\nreturn s.name",
    "find part as p\nfollow p contains component upto any as c\nreturn c.name",
    "find part as p\nfollow p contains component upto 3 as c\nreturn c.name",
    "find part as p\nfollow p supplied_by source as s where via.start_year > 2000\nreturn s.name",
    "find part as p\nor\nfind product as p\nreturn p.name",
    "find part as p\ngroup by p.unit_cost as g\ncount distinct g.p as n\nkeep g where n > 2\nreturn g.key, n order by n desc limit 5",
    "find part as p\nreturn distinct p.name",
    "find part as p\nreturn p.name budget 500 tokens",
    "find p1 as a\nfind p2 as b\ncompute a.x minus b.y as diff\nreturn diff",
    "schema",
    'assert part {name: "Anode", unit_cost: 0.4} as p',
    'assert part {name: "Anode"} source doc:x.pdf as p',
    "assert edge supplied_by(item: p, source: s)",
    "merge a, b",
    "merge a, b prefer newest",
    'distinct a, b reason "different firms"',
    'retire a reason "gone"',
    'flag a reason "bad answer"',
    "derive class widget from entity with {sku: str}",
    "derive class widget from entity with {sku: str} quota 50",
    "derive edge fits(part: widget, whole: widget)",
    'compact g as summary {name: "all of them"}',
    'refine b into row with {sku: col "SKU"} as r',
]


def _no_lines(stmts):
    for s in stmts:
        s.line = 0
    return stmts


@pytest.mark.parametrize("program", PROGRAMS)
def test_rendering_a_program_reparses_to_the_same_program(program):
    once = _no_lines(parse(program))
    twice = _no_lines(parse(canonical(program)))
    assert once == twice, canonical(program)


@pytest.mark.parametrize("program", PROGRAMS)
def test_rendering_is_idempotent(program):
    assert canonical(canonical(program)) == canonical(program)


def test_the_two_spellings_of_a_condition_agree():
    """The whole point: the redundant form and the plain one are one string."""
    qualified = canonical(
        'find part as p\nfollow p supplied_by source as s where s.country = "DE"\nreturn s.name'
    )
    plain = canonical(
        'find part as p\nfollow p supplied_by source where country = "DE" as s\nreturn s.name'
    )
    assert qualified == plain


def test_where_before_and_after_as_agree():
    assert canonical('find part where name = "A" as p\nreturn p.name') == canonical(
        'find part as p where name = "A"\nreturn p.name'
    )


def test_an_integral_float_and_an_integer_agree():
    assert canonical(
        "find part as p where unit_cost > 3.0\nreturn p.name"
    ) == canonical("find part as p where unit_cost > 3\nreturn p.name")


def test_the_default_budget_is_not_written():
    assert "budget" not in canonical("find part as p\nreturn p.name budget 2000 tokens")


def test_upto_one_is_a_plain_follow():
    assert "upto" not in canonical(
        "find part as p\nfollow p contains component upto 1 as c\nreturn c.name"
    )

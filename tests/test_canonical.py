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


def test_every_generated_query_round_trips():
    """Real model output is the only corpus that finds the cases a
    handwritten list does not think of."""
    import json
    from pathlib import Path

    frozen = sorted(
        (Path(__file__).resolve().parents[1] / "eval/out/public").glob("queries-*.json")
    )
    if not frozen:
        pytest.skip("no frozen query file checked in")
    queries = [q for f in frozen for q in json.loads(f.read_text()).values()]
    assert len(queries) > 100, "the corpus should be the whole test set"
    checked = 0
    for q in queries:
        try:
            once = _no_lines(parse(q))
        except Exception:
            continue  # a query the model got wrong is not this test's business
        twice = _no_lines(parse(canonical(q)))
        assert once == twice, q
        checked += 1
    assert checked > 100


@pytest.mark.parametrize(
    "value",
    ['say "hi"', "back\\slash", 'both " and \\', "it's", "plain", "café"],
)
def test_a_string_with_a_quote_or_a_backslash_round_trips(value):
    """The printer has to redo the escapes the parser undid, or it emits
    text that does not parse."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    program = f'find part where name = "{escaped}" as p\nreturn p.name'
    assert _no_lines(parse(canonical(program))) == _no_lines(parse(program))
    assert parse(canonical(program))[0].cond[0][1].value == value


@pytest.mark.parametrize(
    "program",
    [
        'retire a reason "he said \\"no\\""',
        'flag a reason "path C:\\\\tmp"',
        'distinct a, b reason "one \\" quote"',
        'refine b into row with {sku: col "the \\"SKU\\" column"} as r',
        'assert part {name: "say \\"hi\\""} as p',
    ],
)
def test_every_quoted_field_round_trips(program):
    """Four other renderers wrote a bare string into double quotes."""
    assert _no_lines(parse(canonical(program))) == _no_lines(parse(program))

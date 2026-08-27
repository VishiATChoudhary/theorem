"""Property-based hardening tests (Hypothesis).

Invariants, not examples: the parser and session must be total (an error
string or a typed error, never an unhandled exception), null ordering and
budget caps must hold for all inputs, and a store must reopen from any
crash-truncated WAL.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from theorem.engine.executor import _fold, _sorted_rows, count_tokens
from theorem.engine.storage import Store
from theorem.parser import ParseError, parse
from theorem.schema import Schema
from theorem.session import Session

# ---- parser totality -------------------------------------------------


@given(st.text(max_size=300))
@settings(max_examples=300)
def test_parse_total(text):
    """parse() either returns statements or raises ParseError. Nothing else."""
    try:
        parse(text)
    except ParseError:
        pass


@given(
    st.text(
        alphabet='find follow group by as where return budget \n"#@{}(),:.',
        max_size=200,
    )
)
@settings(max_examples=300)
def test_parse_total_keyword_soup(text):
    """Keyword-dense fuzz: exercises deeper parser paths than raw unicode."""
    try:
        parse(text)
    except ParseError:
        pass


# ---- session totality ------------------------------------------------


@given(st.text(max_size=200))
@settings(max_examples=100, deadline=None)
def test_session_run_total(tmp_path_factory, text):
    """Session.run returns a string for any input; errors are messages."""
    db = tmp_path_factory.mktemp("db")
    sess = Session(db / "s", Schema.supply_chain())
    out = sess.run(text)
    assert isinstance(out, str)


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_ ", min_size=1, max_size=30))
@settings(max_examples=100, deadline=None)
def test_unknown_class_always_rejected(tmp_path_factory, word):
    """find <unknown-class> never executes; the error names the line."""
    cls = word.strip().split(" ")[0] or "x"
    schema = Schema.supply_chain()
    if cls in schema.classes or cls in ("nodes", "class", "dup_candidates"):
        return
    db = tmp_path_factory.mktemp("db")
    sess = Session(db / "s", schema)
    out = sess.run(f"find {cls} as x\nreturn x.name")
    assert "line 1" in out
    assert "nothing was executed" in out


# ---- null ordering ---------------------------------------------------


@given(
    st.lists(st.one_of(st.none(), st.integers(-100, 100)), max_size=30),
    st.booleans(),
)
def test_nulls_sort_last_both_directions(values, desc):
    rows = [{"v": v} for v in values]
    out = _sorted_rows(rows, lambda r: r["v"], desc)
    got = [r["v"] for r in out]
    n_null = sum(1 for v in got if v is None)
    if n_null:
        assert all(v is None for v in got[-n_null:])
    present = [v for v in got if v is not None]
    assert present == sorted(present, reverse=desc)


# ---- accent folding --------------------------------------------------


@given(st.text(max_size=50))
def test_fold_idempotent(s):
    assert _fold(_fold(s)) == _fold(s)


@given(st.text(max_size=50))
def test_fold_case_insensitive(s):
    assert _fold(s.upper()) == _fold(s.lower())


# ---- budget boundaries -----------------------------------------------


@given(st.integers(1, 200))
@settings(max_examples=30, deadline=None)
def test_budget_caps_output(tmp_path_factory, budget):
    """Serialized result stays within budget or carries a continuation."""
    db = tmp_path_factory.mktemp("db")
    sess = Session(db / "s", Schema.supply_chain())
    lines = []
    for i in range(40):
        lines.append(
            f'assert product {{name: "Product Number {i:03d}", launch_year: {2000 + i}}} as p{i}'
        )
    sess.run("\n".join(lines))
    out = sess.run(f"find product as p\nreturn p.name budget {budget} tokens")
    assert isinstance(out, str)
    if count_tokens(out) > budget:
        assert "continue @c" in out or "truncated" in out


# ---- WAL crash recovery ----------------------------------------------


@given(st.integers(0, 400))
@settings(max_examples=50, deadline=None)
def test_reopen_after_wal_truncation(tmp_path_factory, cut):
    """A store whose WAL lost its tail (torn write) must still open,
    recovering the longest valid prefix."""
    db = tmp_path_factory.mktemp("db") / "s"
    store = Store(db)
    for i in range(5):
        nid = store.next_id("product")
        store.apply(
            {"op": "put_node", "id": nid, "cls": "product", "props": {"name": f"p{i}"}}
        )
    raw = store.wal_path.read_bytes()
    store.wal_path.write_bytes(raw[: min(cut, len(raw))])
    reopened = Store(db)
    assert len(reopened.nodes) <= 5
    # every fully-written record before the cut must survive
    kept_lines = raw[: min(cut, len(raw))].count(b"\n")
    assert len(reopened.nodes) >= kept_lines - 1

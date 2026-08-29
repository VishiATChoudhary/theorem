"""Tokenizer and recursive-descent parser for theorem.

Line-oriented: one statement per logical line. A physical line starting
with whitespace continues the previous logical line. Lines whose first
character is '#' are comments (node ids never start a line).
"""

from __future__ import annotations

import re

from .ast_nodes import (
    Aggregate,
    AssertEdge,
    AssertNode,
    Clause,
    Col,
    Compact,
    Compute,
    Cond,
    Continue,
    DeriveClass,
    DeriveEdge,
    Distinct,
    Find,
    Flag,
    Follow,
    GroupBy,
    Merge,
    Or,
    Refine,
    Retire,
    Return,
    SchemaStmt,
    Stmt,
)

DEFAULT_BUDGET = 2000

AGG_VERBS = {"count", "sum", "avg", "min", "max"}
COMPARISON_OPS = {"=", "!=", ">", ">=", "<", "<=", "contains"}


class ParseError(Exception):
    def __init__(self, line_no: int, msg: str):
        self.line_no = line_no
        super().__init__(f"parse error at line {line_no}: {msg}")


TOKEN_RE = re.compile(
    r"""
    (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<provenance>(?:doc|attach):[^\s,)}]+)
  | (?P<position>@t-[0-9]+)
  | (?P<handle>@c[a-z0-9]+)
  | (?P<nodeid>\#[a-z]+-[a-z0-9]+)
  | (?P<number>-?[0-9]+(?:\.[0-9]+)?)
  | (?P<op>>=|<=|!=|=|>|<)
  | (?P<word>[A-Za-z_][A-Za-z0-9_.]*)
  | (?P<punct>[{}(),:])
    """,
    re.VERBOSE,
)


def tokenize(text: str, line_no: int) -> list[tuple[str, str]]:
    tokens = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise ParseError(line_no, f"unexpected character {text[pos]!r}")
        kind = m.lastgroup
        tokens.append((kind, m.group()))
        pos = m.end()
    return tokens


def logical_lines(text: str):
    """Yield (line_no, joined_text) for each logical line."""
    current: list[str] = []
    start = 0
    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.lstrip()
        # comments are "#" followed by a space (or a lone "#"); node ids
        # like #p-71002 on continuation lines are NOT comments
        is_comment = stripped.startswith("# ") or stripped == "#"
        if not raw.strip() or is_comment or (not raw[0].isspace() and raw[0] == "#"):
            continue
        if raw[0].isspace() and current:
            current.append(raw.strip())
        else:
            if current:
                yield start, " ".join(current)
            current = [raw.strip()]
            start = i
    if current:
        yield start, " ".join(current)


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], line_no: int):
        self.tokens = tokens
        self.i = 0
        self.line_no = line_no

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def at_word(self, *words: str) -> bool:
        t = self.peek()
        return t is not None and t[0] == "word" and t[1] in words

    def next(self) -> tuple[str, str]:
        t = self.peek()
        if t is None:
            raise ParseError(self.line_no, "expected more input, statement ended early")
        self.i += 1
        return t

    def expect_word(self, *words: str) -> str:
        t = self.peek()
        if t is None or t[0] != "word" or (words and t[1] not in words):
            want = " or ".join(f"'{w}'" for w in words) if words else "a name"
            got = t[1] if t else "end of line"
            raise ParseError(self.line_no, f"expected {want}, got {got!r}")
        self.i += 1
        return t[1]

    def expect_punct(self, ch: str) -> None:
        t = self.peek()
        if t is None or t[0] != "punct" or t[1] != ch:
            got = t[1] if t else "end of line"
            raise ParseError(self.line_no, f"expected {ch!r}, got {got!r}")
        self.i += 1

    def expect_name(self) -> str:
        w = self.expect_word()
        if "." in w:
            raise ParseError(self.line_no, f"expected a plain name, got {w!r}")
        return w

    def expect_end(self) -> None:
        t = self.peek()
        if t is not None:
            raise ParseError(
                self.line_no, f"unexpected trailing input starting at {t[1]!r}"
            )

    # ---- terminals -------------------------------------------------

    def col(self) -> Col:
        w = self.expect_word()
        parts = tuple(w.split("."))
        if len(parts) > 3 or any(not p for p in parts):
            raise ParseError(
                self.line_no,
                f"bad column path {w!r}: 1 to 3 non-empty dot-separated names",
            )
        return parts

    def literal(self, allow_word: bool = False) -> object:
        t = self.next()
        kind, text = t
        if kind == "string":
            return _unquote(text)
        if kind == "number":
            if len(text.lstrip("-").split(".")[0]) > 15:
                raise ParseError(self.line_no, f"number literal {text!r} is too large")
            return float(text) if "." in text else int(text)
        if kind == "provenance":
            if not text.startswith("attach:"):
                raise ParseError(
                    self.line_no,
                    f"{text!r} is not a value; doc: provenance only follows 'source'",
                )
            return text
        if kind == "word":
            if text == "true":
                return True
            if text == "false":
                return False
            if allow_word and "." not in text:
                # bare word in a condition RHS: class names in
                # (find dup_candidates where class = supplier)
                return text
        raise ParseError(self.line_no, f"expected a literal value, got {text!r}")

    def ref(self) -> str:
        t = self.next()
        if t[0] == "nodeid":
            return t[1]
        if t[0] == "word" and "." not in t[1]:
            return t[1]
        raise ParseError(
            self.line_no, f"expected a binding name or node id, got {t[1]!r}"
        )

    def string(self) -> str:
        t = self.next()
        if t[0] != "string":
            raise ParseError(self.line_no, f"expected a quoted string, got {t[1]!r}")
        return _unquote(t[1])

    def props(self) -> dict[str, object]:
        self.expect_punct("{")
        out: dict[str, object] = {}
        while True:
            key = self.expect_name()
            self.expect_punct(":")
            out[key] = self.literal()
            t = self.peek()
            if t == ("punct", ","):
                self.i += 1
                continue
            self.expect_punct("}")
            return out

    def mapping(self) -> dict[str, str]:
        self.expect_punct("{")
        out: dict[str, str] = {}
        while True:
            key = self.expect_name()
            self.expect_punct(":")
            self.expect_word("col")
            out[key] = self.string()
            t = self.peek()
            if t == ("punct", ","):
                self.i += 1
                continue
            self.expect_punct("}")
            return out

    def propdecls(self) -> dict[str, str]:
        self.expect_punct("{")
        out: dict[str, str] = {}
        if self.peek() == ("punct", "}"):
            self.i += 1
            return out
        while True:
            key = self.expect_name()
            self.expect_punct(":")
            out[key] = self.expect_word("str", "int", "float", "bool")
            t = self.peek()
            if t == ("punct", ","):
                self.i += 1
                continue
            self.expect_punct("}")
            return out

    def cond(self) -> Cond:
        out: Cond = []
        joiner = "and"
        while True:
            col = self.col()
            t = self.peek()
            if t is None or (
                t[0] != "op" and not (t[0] == "word" and t[1] == "contains")
            ):
                got = t[1] if t else "end of line"
                raise ParseError(
                    self.line_no, f"expected a comparison operator, got {got!r}"
                )
            self.i += 1
            op = t[1]
            if op not in COMPARISON_OPS:
                raise ParseError(self.line_no, f"unknown operator {op!r}")
            value = self.literal(allow_word=True)
            out.append((joiner, Clause(col, op, value)))
            if self.at_word("and", "or"):
                joiner = self.next()[1]
                continue
            return out

    def order_by_opt(self) -> tuple[Col | None, bool]:
        if not self.at_word("order"):
            return None, False
        self.next()
        self.expect_word("by")
        col = self.col()
        desc = False
        if self.at_word("desc"):
            self.next()
            desc = True
        return col, desc

    def _int(self, t: tuple[str, str], what: str, minimum: int) -> int:
        if t[0] != "number" or "." in t[1]:
            raise ParseError(self.line_no, f"expected an integer {what}, got {t[1]!r}")
        if len(t[1].lstrip("-")) > 12:
            raise ParseError(self.line_no, f"{what} {t[1]!r} is too large")
        value = int(t[1])
        if value < minimum:
            raise ParseError(
                self.line_no, f"{what} must be at least {minimum}, got {value}"
            )
        return value

    def budget_opt(self) -> int | None:
        if not self.at_word("budget"):
            return None
        self.next()
        value = self._int(self.next(), "token budget", 1)
        self.expect_word("tokens")
        return value

    def source_opt(self) -> str | None:
        if not self.at_word("source"):
            return None
        self.next()
        t = self.next()
        if t[0] != "provenance":
            raise ParseError(
                self.line_no, f"expected doc:/attach: provenance, got {t[1]!r}"
            )
        return t[1]

    # ---- statements ------------------------------------------------

    def statement(self) -> Stmt:
        verb = self.expect_word()
        method = getattr(self, f"parse_{verb}", None)
        if verb in AGG_VERBS:
            stmt = self.parse_aggregate(verb)
        elif method is None or verb == "aggregate":
            # "aggregate" would resolve to the internal parse_aggregate
            # helper, which needs an op; it is not a verb itself
            raise ParseError(self.line_no, f"unknown verb {verb!r}")
        else:
            stmt = method()
        self.expect_end()
        stmt.line = self.line_no
        return stmt

    def _trailing_where(self, cond: Cond) -> Cond:
        """Accept `where` after `as` as well as before it.

        Both orders read naturally and people reach for either; rejecting
        one of them teaches nothing and costs a whole query.
        """
        if self.at_word("where"):
            if cond:
                raise ParseError(
                    self.line_no,
                    "two where clauses on one line; combine them with 'and'",
                )
            self.next()
            return self.cond()
        return cond

    def parse_find(self) -> Find:
        target = self.expect_name()
        cond: Cond = []
        if self.at_word("where"):
            self.next()
            cond = self.cond()
        order_by, desc = self.order_by_opt()
        self.expect_word("as")
        name = self.expect_name()
        cond = self._trailing_where(cond)
        if order_by is None:
            order_by, desc = self.order_by_opt()
        return Find(target, cond, name, order_by=order_by, desc=desc)

    def parse_follow(self) -> Follow:
        src = self.expect_name()
        edge = self.expect_name()
        role = self.expect_name()
        cond: Cond = []
        if self.at_word("where"):
            self.next()
            cond = self.cond()
        self.expect_word("as")
        name = self.expect_name()
        cond = self._trailing_where(cond)
        return Follow(src, edge, role, name, cond=cond)

    def parse_or(self) -> Or:
        return Or()

    def parse_group(self) -> GroupBy:
        self.expect_word("by")
        col = self.col()
        self.expect_word("as")
        name = self.expect_name()
        return GroupBy(col, name)

    def parse_aggregate(self, op: str) -> Aggregate:
        distinct = False
        if self.at_word("distinct"):
            self.next()
            distinct = True
        col = self.col()
        self.expect_word("as")
        name = self.expect_name()
        return Aggregate(op, distinct, col, name)

    def parse_compute(self) -> Compute:
        left = self.col()
        op = self.expect_word("plus", "minus", "times", "over", "same")
        right = self.col()
        self.expect_word("as")
        name = self.expect_name()
        return Compute(left, op, right, name)

    def parse_return(self) -> Return:
        cols = [self.col()]
        while self.peek() == ("punct", ","):
            self.next()
            cols.append(self.col())
        order_by, desc = self.order_by_opt()
        limit = None
        if self.at_word("limit"):
            self.next()
            limit = self._int(self.next(), "limit", 0)
        budget = self.budget_opt()
        after = None
        if self.at_word("after"):
            self.next()
            t = self.next()
            if t[0] != "position":
                raise ParseError(
                    self.line_no, f"expected a position like @t-42, got {t[1]!r}"
                )
            after = t[1]
        return Return(
            cols,
            order_by,
            desc,
            limit,
            DEFAULT_BUDGET if budget is None else budget,
            after,
        )

    def parse_continue(self) -> Continue:
        t = self.next()
        if t[0] != "handle":
            raise ParseError(
                self.line_no, f"expected a continuation handle like @c81f, got {t[1]!r}"
            )
        budget = self.budget_opt()
        return Continue(t[1], DEFAULT_BUDGET if budget is None else budget)

    def parse_assert(self) -> Stmt:
        if self.at_word("edge"):
            self.next()
            edge = self.expect_name()
            self.expect_punct("(")
            role_refs: dict[str, str] = {}
            for i in range(2):
                role = self.expect_name()
                self.expect_punct(":")
                role_refs[role] = self.ref()
                if i == 0:
                    self.expect_punct(",")
            self.expect_punct(")")
            source = self.source_opt()
            return AssertEdge(edge, role_refs, source)
        cls = self.expect_name()
        props = self.props()
        source = self.source_opt()
        self.expect_word("as")
        name = self.expect_name()
        return AssertNode(cls, props, source, name)

    def parse_merge(self) -> Merge:
        a = self.ref()
        self.expect_punct(",")
        b = self.ref()
        policy = "newest"
        if self.at_word("prefer"):
            self.next()
            which = self.expect_word("newest", "source")
            if which == "source":
                t = self.next()
                if t[0] != "provenance":
                    raise ParseError(
                        self.line_no,
                        f"expected provenance after 'prefer source', got {t[1]!r}",
                    )
                policy = f"source {t[1]}"
            else:
                policy = "newest"
        return Merge(a, b, policy)

    def parse_distinct(self) -> Distinct:
        a = self.ref()
        self.expect_punct(",")
        b = self.ref()
        self.expect_word("reason")
        return Distinct(a, b, self.string())

    def parse_refine(self) -> Refine:
        ref = self.ref()
        self.expect_word("into")
        cls = self.expect_name()
        self.expect_word("with")
        mapping = self.mapping()
        self.expect_word("as")
        name = self.expect_name()
        return Refine(ref, cls, mapping, name)

    def parse_compact(self) -> Compact:
        src = self.expect_name()
        self.expect_word("as")
        name = self.expect_name()
        props = self.props()
        return Compact(src, name, props)

    def parse_retire(self) -> Retire:
        ref = self.ref()
        self.expect_word("reason")
        return Retire(ref, self.string())

    def parse_flag(self) -> Flag:
        ref = self.ref()
        self.expect_word("reason")
        return Flag(ref, self.string())

    def parse_derive(self) -> Stmt:
        if self.at_word("edge"):
            self.next()
            name = self.expect_name()
            self.expect_punct("(")
            roles: dict[str, str] = {}
            while True:
                role = self.expect_name()
                self.expect_punct(":")
                roles[role] = self.expect_name()
                t = self.peek()
                if t == ("punct", ","):
                    self.i += 1
                    continue
                self.expect_punct(")")
                break
            if len(roles) != 2:
                raise ParseError(
                    self.line_no,
                    f"derive edge {name} needs exactly two roles, got {len(roles)}",
                )
            return DeriveEdge(name, roles)
        self.expect_word("class")
        name = self.expect_name()
        self.expect_word("from")
        base = self.expect_name()
        self.expect_word("with")
        props = self.propdecls()
        quota: int | None = None
        dedup: float | None = None
        while self.at_word("quota") or self.at_word("dedup"):
            clause = self.next()[1]
            if clause == "quota":
                quota = self._int(self.next(), "quota", 1)
            else:
                t = self.next()
                if t[0] != "number":
                    raise ParseError(
                        self.line_no, f"expected a dedup threshold, got {t[1]!r}"
                    )
                value = float(t[1])
                if not (0 < value <= 1):
                    raise ParseError(
                        self.line_no,
                        f"dedup threshold must be in (0, 1], got {value}",
                    )
                dedup = value
        return DeriveClass(name, base, props, quota=quota, dedup=dedup)

    def parse_schema(self) -> SchemaStmt:
        return SchemaStmt()


def _unquote(s: str) -> str:
    return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")


def parse(text: str) -> list[Stmt]:
    stmts = []
    for line_no, logical in logical_lines(text):
        tokens = tokenize(logical, line_no)
        stmts.append(_Parser(tokens, line_no).statement())
    for i, stmt in enumerate(stmts):
        if not isinstance(stmt, Or):
            continue
        # `or` joins two branches, so it needs one on each side. A
        # dangling one is almost always a half-finished edit.
        prev = stmts[i - 1] if i else None
        nxt = stmts[i + 1] if i + 1 < len(stmts) else None
        if prev is None or isinstance(prev, Or):
            raise ParseError(stmt.line, "'or' needs a branch before it")
        if nxt is None or isinstance(nxt, Or):
            raise ParseError(stmt.line, "'or' needs a branch after it")
    return stmts

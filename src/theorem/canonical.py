"""Render a parsed program back to its one canonical spelling.

The language has exactly one way to write each operation, so two correct
answers to the same question are the same program. That is what makes a
plan cache and an audit log possible. It held of the text until the
parser started accepting one redundant spelling, a condition qualified by
the binding its own statement creates, and normalizing it away.

Printing the parse restores the property at the level a cache can use:

    canonical(query) == canonical(other)   iff   they are the same program

Round-tripping is the test that keeps this honest. `parse(canonical(p))`
must equal `parse(p)` for every program, which is checked against every
query the benchmark has ever generated.
"""

from __future__ import annotations

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
    Keep,
    Merge,
    Or,
    Refine,
    Retire,
    Return,
    SchemaStmt,
    Stmt,
)


class CanonicalError(Exception):
    """A statement this printer does not know how to render."""


def canonical(program: str) -> str:
    """The canonical text of a program, given its text."""
    from .parser import parse

    return render(parse(program))


def render(stmts: list[Stmt]) -> str:
    return "\n".join(render_stmt(s) for s in stmts)


def _col(col: Col) -> str:
    return ".".join(col)


def _quoted(v: str) -> str:
    """A string literal, with the escapes the parser undoes put back.

    Backslash first, so escaping a quote does not double the backslash
    that escapes it.
    """
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _literal(v: object) -> str:
    if type(v).__name__ == "_Missing":
        return "none"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return _quoted(v)
    if isinstance(v, float) and v.is_integer():
        # 3.0 and 3 compare equal and mean the same filter; one spelling.
        return str(int(v))
    return str(v)


def _clause(c: Clause) -> str:
    return f"{_col(c.col)} {c.op} {_literal(c.value)}"


def _cond(cond: Cond) -> str:
    out = []
    for i, (joiner, clause) in enumerate(cond):
        out.append(_clause(clause) if i == 0 else f"{joiner} {_clause(clause)}")
    return " ".join(out)


def _where(cond: Cond) -> str:
    return f" where {_cond(cond)}" if cond else ""


def _order(col: Col | None, desc: bool) -> str:
    if col is None:
        return ""
    return f" order by {_col(col)}" + (" desc" if desc else "")


def _props(props: dict) -> str:
    return "{" + ", ".join(f"{k}: {_literal(v)}" for k, v in props.items()) + "}"


def render_stmt(stmt: Stmt) -> str:
    match stmt:
        case Find(target=t, cond=cond, name=n, order_by=ob, desc=d):
            # The condition comes before `as`, which is the spelling the
            # grammar leads with; the trailing form parses to the same tree.
            return f"find {t}{_where(cond)}{_order(ob, d)} as {n}"
        case Follow(
            src=src, edge=e, role=r, name=n, cond=cond, optional=opt, upto=upto
        ):
            reach = ""
            if upto == 0:
                reach = " upto any"
            elif upto is not None and upto != 1:
                reach = f" upto {upto}"
            tail = " or none" if opt else ""
            return f"follow {src} {e} {r}{_where(cond)}{reach} as {n}{tail}"
        case Or():
            return "or"
        case GroupBy(col=col, name=n):
            return f"group by {_col(col)} as {n}"
        case Aggregate(op=op, distinct=dist, col=col, name=n):
            return f"{op}{' distinct' if dist else ''} {_col(col)} as {n}"
        case Keep(name=n, cond=cond):
            return f"keep {n} where {_cond(cond)}"
        case Compute(left=lhs, op=op, right=rhs, name=n):
            return f"compute {_col(lhs)} {op} {_col(rhs)} as {n}"
        case Return(
            cols=cols,
            order_by=ob,
            desc=d,
            limit=lim,
            budget=budget,
            after=after,
            distinct=dist,
        ):
            out = "return" + (" distinct" if dist else "")
            out += " " + ", ".join(_col(c) for c in cols)
            out += _order(ob, d)
            if lim is not None:
                out += f" limit {lim}"
            if budget != 2000:  # the default is not written
                out += f" budget {budget} tokens"
            if after is not None:
                out += f" after {after}"
            return out
        case Continue(handle=h, budget=budget):
            out = f"continue {h}"
            if budget != 2000:
                out += f" budget {budget} tokens"
            return out
        case SchemaStmt():
            return "schema"
        case AssertNode(cls=cls, props=props, source=src, name=n):
            out = f"assert {cls} {_props(props)}"
            if src:
                out += f" source {src}"
            return out + f" as {n}"
        case AssertEdge(edge=e, role_refs=roles, source=src):
            args = ", ".join(f"{r}: {v}" for r, v in roles.items())
            out = f"assert edge {e}({args})"
            return out + (f" source {src}" if src else "")
        case Merge(a=a, b=b, policy=policy):
            out = f"merge {a}, {b}"
            return out + (f" prefer {policy}" if policy else "")
        case Distinct(a=a, b=b, reason=reason):
            return f"distinct {a}, {b} reason {_quoted(reason)}"
        case Refine(ref=ref, into_cls=cls, mapping=mapping, name=n):
            cols = ", ".join(f"{k}: col {_quoted(v)}" for k, v in mapping.items())
            return f"refine {ref} into {cls} with {{{cols}}} as {n}"
        case Compact(src=src, name=n, props=props):
            return f"compact {src} as {n} {_props(props)}"
        case Retire(ref=ref, reason=reason):
            return f"retire {ref} reason {_quoted(reason)}"
        case Flag(ref=ref, reason=reason):
            return f"flag {ref} reason {_quoted(reason)}"
        case DeriveClass(name=n, base=base, props=props, quota=quota, dedup=dedup):
            decls = ", ".join(f"{k}: {v}" for k, v in props.items())
            out = f"derive class {n} from {base} with {{{decls}}}"
            if quota is not None:
                out += f" quota {quota}"
            if dedup is not None:
                out += f" dedup {dedup}"
            return out
        case DeriveEdge(name=n, roles=roles):
            args = ", ".join(f"{r}: {c}" for r, c in roles.items())
            return f"derive edge {n}({args})"
    raise CanonicalError(f"cannot render {type(stmt).__name__}")

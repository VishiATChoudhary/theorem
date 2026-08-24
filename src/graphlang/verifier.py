"""Verify-before-execute: whole-program validation against the live schema.

Nothing runs until every statement checks out. Errors name the line, offer
nearest-name suggestions, and always end with "nothing was executed."
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from .ast_nodes import (
    Aggregate,
    AssertEdge,
    AssertNode,
    Col,
    Compact,
    Cond,
    Continue,
    DeriveClass,
    Distinct,
    Find,
    Flag,
    GroupBy,
    Merge,
    Refine,
    Retire,
    Return,
    SchemaStmt,
    Stmt,
    Follow,
)
from .schema import Schema

# Pseudo-columns available on any node binding in return/where clauses.
NODE_PSEUDO_PROPS = {"class", "health", "lineage", "id", "state"}
HEALTH_SUBSCORES = {"loss", "query", "structure", "staleness"}
DUP_CANDIDATE_PROPS = {"class", "score", "a", "b", "evidence"}
SPECIAL_TARGETS = {"nodes", "dup_candidates", "class"}


class VerifyError(Exception):
    def __init__(self, line_no: int, msg: str):
        self.line_no = line_no
        super().__init__(f"error: {msg} in line {line_no}\nnothing was executed.")


@dataclass
class Plan:
    """v0 plan is the verified statement plus its binding-type annotation."""

    stmt: Stmt
    binding_types: dict[str, str]  # env snapshot after this statement


def _suggest(name: str, options) -> str:
    opts = list(options)
    close = difflib.get_close_matches(name, opts, n=2, cutoff=0.5)
    if close:
        return " did you mean: " + ", ".join(close) + "?"
    if opts and len(opts) <= 6:
        return " did you mean one of: " + ", ".join(sorted(opts)) + "?"
    return ""


def verify(stmts: list[Stmt], schema: Schema,
           env: dict[str, str] | None = None) -> list[Plan]:
    # binding name -> class name | "nodes" | "dup_candidates" | "class"
    #                 | "group:<col>" | "value:<agg>"
    env = dict(env) if env else {}
    plans: list[Plan] = []
    for stmt in stmts:
        _verify_stmt(stmt, schema, env)
        plans.append(Plan(stmt, dict(env)))
    return plans


def _bind(env: dict[str, str], name: str, typ: str, line: int) -> None:
    if name in env:
        raise VerifyError(line, f'name "{name}" is already bound')
    env[name] = typ


def _check_class(schema: Schema, name: str, line: int) -> None:
    if name not in schema.classes:
        raise VerifyError(
            line, f'unknown class "{name}".{_suggest(name, schema.classes)}')


def _check_cond(cond: Cond, schema: Schema, env: dict[str, str],
                target: str, line: int) -> None:
    for _joiner, clause in cond:
        _check_col_in_context(clause.col, schema, env, target, line)


def _check_col_in_context(col: Col, schema: Schema, env: dict[str, str],
                          target: str, line: int) -> None:
    """Check a column path used in a where/order-by clause of find over `target`."""
    head = col[0]
    if target == "dup_candidates":
        if head not in DUP_CANDIDATE_PROPS:
            raise VerifyError(
                line, f'unknown dup-candidate field "{head}".{_suggest(head, DUP_CANDIDATE_PROPS)}')
        return
    if target == "class":
        return  # schema introspection: any field allowed in v0
    if head == "health":
        if len(col) < 2 or col[1] not in HEALTH_SUBSCORES:
            sub = col[1] if len(col) > 1 else ""
            raise VerifyError(
                line, f'unknown health subscore "{sub}".{_suggest(sub, HEALTH_SUBSCORES)}')
        return
    if head in NODE_PSEUDO_PROPS or head == "query_traffic":
        return
    if target == "nodes":
        return  # any property name may exist on some class
    props = schema.all_props(target)
    if head not in props:
        raise VerifyError(
            line, f'unknown property "{head}" on class {target}.{_suggest(head, props)}')


def _check_bound_col(col: Col, schema: Schema, env: dict[str, str], line: int) -> None:
    """Check a column path rooted at a binding (return/group/aggregate)."""
    head = col[0]
    if head not in env:
        raise VerifyError(line, f'"{head}" is not bound.{_suggest(head, env)}')
    if len(col) == 1:
        return
    typ = env[head]
    prop = col[1]
    if typ.startswith("group:"):
        return  # g.<member column>: checked against group source below by executor
    if typ in ("nodes", "dup_candidates", "class") or typ.startswith("value:"):
        return
    if prop in NODE_PSEUDO_PROPS or prop == "query_traffic":
        return
    if typ in schema.classes:
        props = schema.all_props(typ)
        if prop not in props:
            raise VerifyError(
                line, f'unknown property "{prop}" on class {typ}.{_suggest(prop, props)}')


def _ref_type(ref: str, env: dict[str, str], line: int) -> str | None:
    """A ref is a binding name or a literal node id. Node ids resolve at run time."""
    if ref.startswith("#"):
        return None
    if ref not in env:
        raise VerifyError(line, f'"{ref}" is not bound.{_suggest(ref, env)}')
    return env[ref]


def _verify_stmt(stmt: Stmt, schema: Schema, env: dict[str, str]) -> None:
    line = stmt.line
    match stmt:
        case Find(target=target, cond=cond, name=name, order_by=order_by):
            if target not in SPECIAL_TARGETS:
                _check_class(schema, target, line)
            _check_cond(cond, schema, env, target, line)
            if order_by is not None:
                _check_col_in_context(order_by, schema, env, target, line)
            _bind(env, name, target, line)

        case Follow(src=src, edge=edge, role=role, name=name, cond=cond):
            if src not in env:
                raise VerifyError(line, f'"{src}" is not bound.{_suggest(src, env)}')
            if edge not in schema.edges:
                raise VerifyError(
                    line, f'unknown edge type "{edge}".{_suggest(edge, schema.edges)}')
            edef = schema.edges[edge]
            if role not in edef.roles:
                raise VerifyError(
                    line,
                    f'unknown role "{role}" on edge {edge}; roles are '
                    + ", ".join(f"{r} ({c})" for r, c in edef.roles.items())
                    + f".{_suggest(role, edef.roles)}")
            src_cls = env[src]
            arrival_cls = edef.roles[role]
            other = edef.other_role(role)
            other_cls = edef.roles[other]
            if src_cls in schema.classes and arrival_cls != other_cls:
                # heterogeneous edge: the source must sit at the other role
                if src_cls != other_cls and src_cls == arrival_cls:
                    raise VerifyError(
                        line,
                        f'type error: "{src}" is a {src_cls}, which already occupies role '
                        f'"{role}"; to traverse {edge} from {src_cls} arrive at role "{other}"')
                if src_cls != other_cls and src_cls != arrival_cls:
                    raise VerifyError(
                        line,
                        f"type error: {edge} connects {other_cls} ({other}) to "
                        f'{arrival_cls} ({role}); "{src}" is a {src_cls}')
            _check_cond(cond, schema, env, arrival_cls, line)
            _bind(env, name, arrival_cls, line)

        case GroupBy(col=col, name=name):
            _check_bound_col(col, schema, env, line)
            _bind(env, name, f"group:{'.'.join(col)}", line)

        case Aggregate(op=op, col=col, name=name):
            head = col[0]
            if head not in env:
                raise VerifyError(line, f'"{head}" is not bound.{_suggest(head, env)}')
            if not env[head].startswith("group:"):
                raise VerifyError(
                    line,
                    f'{op} consumes a group; "{head}" is not a group binding. '
                    f"group by <column> as <name> first")
            _bind(env, name, f"value:{op}", line)

        case Return(cols=cols, order_by=order_by):
            for col in cols:
                _check_bound_col(col, schema, env, line)
            if order_by is not None:
                _check_bound_col(order_by, schema, env, line)

        case Continue():
            pass  # handle validity is a runtime question

        case AssertNode(cls=cls, props=props, name=name):
            _check_class(schema, cls, line)
            all_props = schema.all_props(cls)
            for prop in props:
                if prop not in all_props:
                    raise VerifyError(
                        line, f'unknown property "{prop}" on class {cls}.{_suggest(prop, all_props)}')
            _bind(env, name, cls, line)

        case AssertEdge(edge=edge, role_refs=role_refs):
            if edge not in schema.edges:
                raise VerifyError(
                    line, f'unknown edge type "{edge}".{_suggest(edge, schema.edges)}')
            edef = schema.edges[edge]
            if set(role_refs) != set(edef.roles):
                missing = set(edef.roles) - set(role_refs)
                extra = set(role_refs) - set(edef.roles)
                parts = []
                if extra:
                    e0 = sorted(extra)[0]
                    parts.append(f'unknown role "{e0}"{_suggest(e0, edef.roles)}')
                if missing:
                    parts.append(f'missing role "{sorted(missing)[0]}"')
                raise VerifyError(line, f"edge {edge}: " + "; ".join(parts))
            for role, ref in role_refs.items():
                typ = _ref_type(ref, env, line)
                want = edef.roles[role]
                if typ is not None and typ in schema.classes and typ != want:
                    raise VerifyError(
                        line, f'role {role} of {edge} takes a {want}; "{ref}" is a {typ}')

        case Merge(a=a, b=b):
            _ref_type(a, env, line)
            _ref_type(b, env, line)

        case Distinct(a=a, b=b):
            _ref_type(a, env, line)
            _ref_type(b, env, line)

        case Refine(ref=ref, into_cls=into_cls, name=name):
            _ref_type(ref, env, line)
            _check_class(schema, into_cls, line)
            _bind(env, name, into_cls, line)

        case Compact(src=src, name=name):
            if src not in env:
                raise VerifyError(line, f'"{src}" is not bound.{_suggest(src, env)}')
            _bind(env, name, env[src], line)

        case Retire(ref=ref) | Flag(ref=ref):
            _ref_type(ref, env, line)

        case DeriveClass(name=name, base=base):
            if base not in schema.classes:
                raise VerifyError(
                    line, f'unknown base class "{base}".{_suggest(base, schema.classes)}')
            if name in schema.classes:
                raise VerifyError(line, f'class "{name}" already exists')

        case SchemaStmt():
            pass

        case _:
            raise VerifyError(line, f"unsupported statement {type(stmt).__name__}")

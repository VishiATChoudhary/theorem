"""Read executor: binding-table semantics over the store, plus result
serialization with token budgets and continuation handles.

A query builds one binding table. find seeds rows, follow extends them
(homomorphism semantics), group/aggregate collapse them, return serializes.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from ..ast_nodes import (
    Aggregate,
    Clause,
    Col,
    Compute,
    Cond,
    Continue,
    Find,
    Follow,
    GroupBy,
    Return,
    SchemaStmt,
)
from ..schema import Schema
from ..verifier import Plan
from . import health
from .storage import Store

TOKEN_DIVISOR = 4


def count_tokens(text: str) -> int:
    return len(text) // TOKEN_DIVISOR


class ExecError(Exception):
    pass


@dataclass
class ReadContext:
    """Session-scoped state: continuation handles."""

    continuations: dict[str, dict] = field(default_factory=dict)
    _counter: int = 0

    def register(self, payload: dict) -> str:
        self._counter += 1
        handle = f"@c{self._counter:x}{len(payload.get('blocks', [])):x}"
        self.continuations[handle] = payload
        return handle


@dataclass
class Table:
    rows: list[dict] = field(default_factory=list)
    # group binding name -> (key col, key kind "identity"|"value")
    group_meta: dict[str, tuple[Col, str]] = field(default_factory=dict)
    grouped: bool = False  # rows are group-rows after first aggregate


def _node_value(store: Store, schema: Schema, node_id: str, prop: str):
    node = store.nodes[store.resolve(node_id)]
    if prop == "class":
        return node.cls
    if prop == "id":
        return node.id
    if prop == "state":
        return node.state
    if prop == "query_traffic":
        return node.traffic
    if prop == "lineage":
        related = [
            rec
            for rec in store.lineage
            if node.id
            in (
                rec.get("survivor"),
                rec.get("absorbed"),
                rec.get("parent"),
                rec.get("child"),
            )
        ]
        origin = f"origin {node.origin}; " if node.origin else ""
        return origin + f"{len(related)} lineage records"
    if prop == "health":
        s = health.scores(store, node.id)
        return "{" + ", ".join(f"{k}: {v:.2f}" for k, v in s.items()) + "}"
    return node.props.get(prop)


def _col_value(store: Store, schema: Schema, row: dict, col: Col):
    head = col[0]
    if head in row:
        value = row[head]
        if len(col) == 1:
            return value
        if isinstance(value, str) and value in store.nodes:
            if col[1] == "health" and len(col) == 3:
                return health.scores(store, value)[col[2]]
            if col[1] == "health" and len(col) == 2:
                return _node_value(store, schema, value, "health")
            return _node_value(store, schema, value, col[1])
        if isinstance(value, dict):  # dup candidate / class row
            return value.get(col[1])
        return value
    if len(col) >= 2 and f"{head}_key" in row and col[1] == "key":
        return row[f"{head}_key"]
    raise ExecError(f"cannot resolve column {'.'.join(col)}")


def _fold(v):
    """Agent-friendly string normalization: casefold + strip accents.
    Agents transliterate names; silently matching nothing is the worse
    failure mode. Numbers pass through untouched."""
    if isinstance(v, str):
        # casefold BEFORE stripping accents: casefold('ß') == 'ss', but
        # NFKD+ascii-ignore deletes 'ß' outright, so the reverse order
        # makes upper/lower forms of the same word fold differently.
        return (
            unicodedata.normalize("NFKD", v.casefold()).encode("ascii", "ignore").decode()
        )
    return v


def _clause_matches(store: Store, schema: Schema, row_value, clause: Clause) -> bool:
    v = row_value
    want = clause.value
    op = clause.op
    if v is None:
        return False
    if isinstance(v, str) or isinstance(want, str):
        v, want = _fold(v), _fold(want)
    try:
        if op == "=":
            return v == want
        if op == "!=":
            return v != want
        if op == ">":
            return v > want
        if op == ">=":
            return v >= want
        if op == "<":
            return v < want
        if op == "<=":
            return v <= want
        if op == "contains":
            return str(want) in str(v)
    except TypeError:
        return False
    raise ExecError(f"unknown operator {op}")


def _eval_cond(store: Store, schema: Schema, cond: Cond, getter) -> bool:
    """and binds tighter than or: evaluate as OR over AND-groups."""
    if not cond:
        return True
    groups: list[list[bool]] = [[]]
    for joiner, clause in cond:
        if joiner == "or":
            groups.append([])
        groups[-1].append(_clause_matches(store, schema, getter(clause.col), clause))
    return any(all(g) for g in groups if g)


def _candidate_rows(store: Store) -> list[dict]:
    rows = []
    for rec in store.dup_ledger:
        pair = frozenset((store.resolve(rec["a"]), store.resolve(rec["b"])))
        if len(pair) < 2 or pair in store.distinct_pairs:
            continue  # already merged or asserted distinct
        rows.append(
            {
                "class": rec["cls"],
                "score": rec["score"],
                "a": rec["a"],
                "b": rec["b"],
                "evidence": rec.get("evidence", ""),
            }
        )
    return rows


def _find_rows(stmt: Find, store: Store, schema: Schema) -> list[dict]:
    name = stmt.name

    def _dict_getter(row):
        return lambda col: row[name].get(col[0])

    if stmt.target == "dup_candidates":
        pool = [{name: rec} for rec in _candidate_rows(store)]
        getter = _dict_getter
    elif stmt.target == "class":
        pool = [
            {
                name: {
                    "name": c.name,
                    "status": c.status,
                    "base": c.base,
                    "quota": c.quota,
                }
            }
            for c in schema.classes.values()
        ]
        getter = _dict_getter
    else:
        if stmt.target == "nodes":
            nodes = [n for n in store.nodes.values()]
        else:
            nodes = [n for n in store.nodes.values() if n.cls == stmt.target]
        pool = [
            {name: n.id}
            for n in nodes
            if n.retired_at is None and store.resolve(n.id) == n.id
        ]

        def getter(row):
            return lambda col: _first_prop(store, schema, row[name], col)

    rows = [r for r in pool if _eval_cond(store, schema, stmt.cond, getter(r))]
    if stmt.order_by is not None:
        rows = _sorted_rows(rows, lambda r: getter(r)(stmt.order_by), stmt.desc)
    return rows


def _first_prop(store: Store, schema: Schema, node_id: str, col: Col):
    if col[0] == "health":
        return health.scores(store, node_id)[col[1]]
    return _node_value(store, schema, node_id, col[0])


def _sort_key(v):
    # mixed types sort by string form; None handled by _sorted_rows
    return (isinstance(v, str), v if v is not None else "")


def _sorted_rows(rows, key, desc: bool):
    """Sort with None values always LAST, in both directions."""
    present = [r for r in rows if key(r) is not None]
    missing = [r for r in rows if key(r) is None]
    return sorted(present, key=lambda r: _sort_key(key(r)), reverse=desc) + missing


def _follow(stmt: Follow, table: Table, store: Store, schema: Schema) -> None:
    edef = schema.edges[stmt.edge]
    arrive_role = stmt.role
    depart_role = edef.other_role(arrive_role)
    new_rows = []
    touched: set[str] = set()
    for row in table.rows:
        src_id = store.resolve(row[stmt.src])
        for edge in store.edges.get(src_id, []):
            if edge.type != stmt.edge or edge.retired_at is not None:
                continue
            if store.resolve(edge.roles[depart_role]) != src_id:
                continue
            dst = store.resolve(edge.roles[arrive_role])
            dst_node = store.nodes.get(dst)
            if dst_node is None or dst_node.retired_at is not None:
                continue
            if edge.id in row.get("__edges__", ()):
                continue  # trail semantics: an edge instance is used once per row
            if stmt.cond and not _eval_cond(
                store,
                schema,
                stmt.cond,
                lambda col, dst=dst: _first_prop(store, schema, dst, col),
            ):
                continue
            touched.add(src_id)
            touched.add(dst)
            new_rows.append(
                {
                    **row,
                    stmt.name: dst,
                    "__edges__": (*row.get("__edges__", ()), edge.id),
                }
            )
    for nid in touched:
        blob = 1 if store.nodes[nid].state == "blob" else 0
        store.apply({"op": "traffic", "id": nid, "n": 1, "blob": blob})
    table.rows = new_rows


def _group(stmt: GroupBy, table: Table, store: Store, schema: Schema) -> None:
    kind = "identity" if len(stmt.col) == 1 else "value"
    table.group_meta[stmt.name] = (stmt.col, kind)


def _agg_compute(op: str, values: list):
    if op == "count":
        return len(values)
    if op == "sum":
        return sum(values)
    if op == "avg":
        return sum(values) / len(values) if values else None
    if op == "min":
        return min(values) if values else None
    if op == "max":
        return max(values) if values else None
    raise ExecError(f"unknown aggregate {op}")


def _global_aggregate(
    stmt: Aggregate, table: Table, store: Store, schema: Schema
) -> None:
    """Aggregate over a plain binding column: collapses the table to one row."""
    prop = stmt.col[1] if len(stmt.col) > 1 else None
    raw = [row.get(stmt.col[0]) for row in table.rows]
    if stmt.distinct:
        seen = []
        for v in raw:
            if v not in seen:
                seen.append(v)
        raw = seen
    values = []
    for v in raw:
        if prop is not None and isinstance(v, str) and v in store.nodes:
            v = _node_value(store, schema, v, prop)
        values.append(v)
    values = [v for v in values if v is not None]
    table.rows = [{stmt.name: _agg_compute(stmt.op, values)}]
    table.group_meta.clear()


def _aggregate(stmt: Aggregate, table: Table, store: Store, schema: Schema) -> None:
    gname = stmt.col[0]
    if gname not in table.group_meta:
        _global_aggregate(stmt, table, store, schema)
        return
    member = stmt.col[1]
    prop = stmt.col[2] if len(stmt.col) > 2 else None
    key_col, kind = table.group_meta[gname]

    if not table.grouped:
        groups: dict = {}
        order: list = []
        for row in table.rows:
            key = _col_value(store, schema, row, key_col)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(row)
        group_rows = []
        for key in order:
            members = groups[key]
            base = {f"{gname}_key": key, f"__members_{gname}": members}
            if kind == "identity":
                base[key_col[0]] = key  # keep the node binding on the group row
            group_rows.append(base)
        table.rows = group_rows
        table.grouped = True

    for row in table.rows:
        members = row[f"__members_{gname}"]
        raw = [m.get(member) for m in members]
        if stmt.distinct:
            seen = []
            for v in raw:
                if v not in seen:
                    seen.append(v)
            raw = seen
        values = []
        for v in raw:
            if prop is not None and isinstance(v, str) and v in store.nodes:
                v = _node_value(store, schema, v, prop)
            values.append(v)
        values = [v for v in values if v is not None]
        row[stmt.name] = _agg_compute(stmt.op, values)


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _render_node_block(store: Store, schema: Schema, node_id: str) -> list[str]:
    node = store.nodes[store.resolve(node_id)]
    shown = {
        k: v for k, v in node.props.items() if k != "name" and not k.startswith("_")
    }
    props = ", ".join(f"{k}: {_fmt(v)}" for k, v in shown.items())
    name = node.props.get("name") or node.props.get("title") or node.id
    lines = [f'{node.cls} "{name}"' + (f" {{{props}}}" if props else "")]
    for edge in store.edges.get(node.id, []):
        if edge.retired_at is not None:
            continue
        roles = list(edge.roles.items())
        (_, subj_id), (_, obj_id) = roles[0], roles[1]
        subj_id, obj_id = store.resolve(subj_id), store.resolve(obj_id)
        if subj_id == node.id:
            other = store.nodes[obj_id]
            arrow = "->"
        else:
            other = store.nodes[subj_id]
            arrow = "<-"
        oname = other.props.get("name") or other.props.get("title") or other.id
        lines.append(f'  {edge.type} {arrow} {other.cls} "{oname}"')
    return lines


def _serialize(
    store: Store, schema: Schema, stmt: Return, table: Table, ctx: ReadContext
) -> str:
    incident = any(
        len(c) == 1
        and table.rows
        and isinstance(table.rows[0].get(c[0]), str)
        and table.rows[0][c[0]] in store.nodes
        for c in stmt.cols
    )

    rows = table.rows
    if stmt.order_by is not None:
        rows = _sorted_rows(
            rows, lambda r: _col_value(store, schema, r, stmt.order_by), stmt.desc
        )
    total = len(rows)
    if stmt.limit is not None:
        rows = rows[: stmt.limit]

    blocks: list[str] = []
    if incident:
        for row in rows:
            block_lines: list[str] = []
            for col in stmt.cols:
                v = _col_value(store, schema, row, col)
                if len(col) == 1 and isinstance(v, str) and v in store.nodes:
                    block_lines.extend(_render_node_block(store, schema, v))
                else:
                    block_lines.append(_fmt(v))
            blocks.append("\n".join(block_lines))
        header_cols = None
    else:
        header_cols = "columns: " + ", ".join(".".join(c) for c in stmt.cols)
        for row in rows:
            blocks.append(
                ", ".join(
                    _fmt(_col_value(store, schema, row, col)) for col in stmt.cols
                )
            )

    return _emit(blocks, total, stmt.budget, header_cols, ctx)


def _emit(
    blocks: list[str],
    total: int,
    budget: int,
    header_cols: str | None,
    ctx: ReadContext,
    already_shown: int = 0,
) -> str:
    shown = []
    used = 0
    overhead = 60 + (len(header_cols) if header_cols else 0)
    budget_chars = max(budget * TOKEN_DIVISOR - overhead, 0)
    for block in blocks:
        cost = len(block) + 1
        if shown and used + cost > budget_chars:
            break
        shown.append(block)
        used += cost
    remaining = blocks[len(shown) :]
    n_shown = len(shown)
    status = "complete" if not remaining else "budget hit"
    header = f"results: {already_shown + n_shown} of {total}, {status}"
    out_lines = [header]
    if header_cols:
        out_lines.append(header_cols)
    out_lines.extend(shown)
    if remaining:
        handle = ctx.register(
            {
                "blocks": remaining,
                "total": total,
                "header_cols": header_cols,
                "shown": already_shown + n_shown,
            }
        )
        out_lines.append(
            f"truncated: {len(remaining)} more. resume with: continue {handle}"
        )
    return "\n".join(out_lines)


def _compute(stmt: Compute, table: Table, store: Store, schema: Schema) -> None:
    for row in table.rows:
        left = _col_value(store, schema, row, stmt.left)
        right = _col_value(store, schema, row, stmt.right)
        if stmt.op == "same":
            if left is None or right is None:
                raise ExecError(
                    f"compute same: {'.'.join(stmt.left if left is None else stmt.right)} "
                    "is unset; cannot compare a missing value"
                )
            row[stmt.name] = _fold(left) == _fold(right)
            continue
        if (
            not isinstance(left, (int, float))
            or not isinstance(right, (int, float))
            or isinstance(left, bool)
            or isinstance(right, bool)
        ):
            raise ExecError(
                f"compute {stmt.op} needs numbers; got "
                f"{type(left).__name__} and {type(right).__name__}"
            )
        if stmt.op == "plus":
            row[stmt.name] = left + right
        elif stmt.op == "minus":
            row[stmt.name] = left - right
        elif stmt.op == "times":
            row[stmt.name] = left * right
        elif stmt.op == "over":
            if right == 0:
                raise ExecError("compute over: division by zero")
            row[stmt.name] = left / right
        else:
            raise ExecError(f"unknown compute op {stmt.op}")


def _apply_pipeline_stmt(stmt, table: Table, store: Store, schema: Schema) -> None:
    if isinstance(stmt, Find):
        found = _find_rows(stmt, store, schema)
        table.rows = _cross(table.rows, found) if table.rows else found
    elif isinstance(stmt, Follow):
        _follow(stmt, table, store, schema)
    elif isinstance(stmt, GroupBy):
        _group(stmt, table, store, schema)
    elif isinstance(stmt, Aggregate):
        _aggregate(stmt, table, store, schema)
    elif isinstance(stmt, Compute):
        _compute(stmt, table, store, schema)
    else:
        raise ExecError(f"cannot run {type(stmt).__name__} in a read pipeline")


def execute_read(
    plans: list[Plan],
    store: Store,
    schema: Schema,
    ctx: ReadContext,
    table: Table | None = None,
) -> str:
    if table is None:
        table = Table()
    output: list[str] = []
    for plan in plans:
        stmt = plan.stmt
        if isinstance(stmt, Return):
            output.append(_serialize(store, schema, stmt, table, ctx))
        elif isinstance(stmt, Continue):
            payload = ctx.continuations.pop(stmt.handle, None)
            if payload is None:
                raise ExecError(f"unknown continuation handle {stmt.handle}")
            output.append(
                _emit(
                    payload["blocks"],
                    payload["total"],
                    stmt.budget,
                    payload["header_cols"],
                    ctx,
                    already_shown=payload["shown"],
                )
            )
        elif isinstance(stmt, SchemaStmt):
            output.append(schema.render())
        else:
            _apply_pipeline_stmt(stmt, table, store, schema)
    return "\n".join(output)


def execute_rows(plans: list[Plan], store: Store, schema: Schema) -> list[list]:
    """Run a read program and return the final Return's rows as plain values.

    Used by the eval harness for machine scoring; ignores budgets.
    """
    table = Table()
    rows_out: list[list] = []
    for plan in plans:
        stmt = plan.stmt
        if isinstance(stmt, Return):
            rows = table.rows
            if stmt.order_by is not None:
                rows = _sorted_rows(
                    rows,
                    lambda r, stmt=stmt: _col_value(store, schema, r, stmt.order_by),
                    stmt.desc,
                )
            if stmt.limit is not None:
                rows = rows[: stmt.limit]

            def plain(v):
                if isinstance(v, str) and v in store.nodes:
                    return store.nodes[v].props.get("name", v)
                return v

            rows_out = [
                [plain(_col_value(store, schema, r, col)) for col in stmt.cols]
                for r in rows
            ]
        elif isinstance(stmt, SchemaStmt):
            continue
        else:
            _apply_pipeline_stmt(stmt, table, store, schema)
    return rows_out


def _cross(rows_a: list[dict], rows_b: list[dict]) -> list[dict]:
    return [{**a, **b} for a in rows_a for b in rows_b]

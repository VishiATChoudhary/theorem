"""Read executor: binding-table semantics over the store, plus result
serialization with token budgets and continuation handles.

A query builds one binding table. find seeds rows, follow extends them
(homomorphism semantics), group/aggregate collapse them, return serializes.
"""

from __future__ import annotations

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
    Or,
    Return,
    SchemaStmt,
)
from ..schema import Schema
from ..verifier import Plan
from . import health
from .storage import Store
from .text import fold

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
    seeded: bool = False  # a find has run; an empty table means zero rows


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
    if len(col) >= 2 and col[1] in row:
        # g.<member>: a binding named through its group. Nothing has
        # collapsed it, so it still reads as the binding itself.
        return _col_value(store, schema, row, col[1:])
    raise ExecError(f"cannot resolve column {'.'.join(col)}")


def _is_none_literal(v) -> bool:
    return type(v).__name__ == "_Missing"


def _fold(v):
    """Agent-friendly string normalization (shared with dedup; see text.py).
    Agents transliterate names; silently matching nothing is the worse
    failure mode. Numbers pass through untouched."""
    return fold(v)


def _clause_matches(store: Store, schema: Schema, row_value, clause: Clause) -> bool:
    v = row_value
    want = clause.value
    op = clause.op
    if _is_none_literal(want):
        # `= none` / `!= none` ask whether the value is there at all,
        # which is the only way to talk about missing data.
        missing = v is None or v == []
        return missing if op == "=" else not missing
    if v is None:
        return False
    if isinstance(v, list):
        # A multi-valued property is asked about one value at a time:
        # "citizenship = Japan" means Japan is one of them. Ordering
        # comparisons have no meaning across a list.
        if op in ("=", "contains"):
            return any(
                _clause_matches(store, schema, item, Clause(clause.col, op, want))
                for item in v
            )
        if op == "!=":
            return not any(
                _clause_matches(store, schema, item, Clause(clause.col, "=", want))
                for item in v
            )
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


def _name_lookup(stmt: Find, store: Store) -> list[str] | None:
    """Node ids that could match a name-equality condition, else None.

    A prefilter only: the caller still evaluates the whole condition on
    every candidate, so this can safely return a superset and matching
    semantics are untouched. Returns None when the condition is not
    purely name equality, which means "no shortcut, read the class".
    """
    if not stmt.cond:
        return None
    for _joiner, clause in stmt.cond:
        if (
            clause.col != ("name",)
            or clause.op != "="
            or not isinstance(clause.value, str)
        ):
            return None
    ids: list[str] = []
    seen: set[str] = set()
    for _joiner, clause in stmt.cond:
        for nid in store.by_name.get((stmt.target, _fold(clause.value)), ()):
            if nid not in seen:
                seen.add(nid)
                ids.append(nid)
    return ids


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
            candidates = _name_lookup(stmt, store)
            nodes = [
                store.nodes[nid]
                for nid in (
                    store.by_class.get(stmt.target, ())
                    if candidates is None
                    else candidates
                )
            ]
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
    """Walk an edge, once or repeatedly.

    `upto N` repeats the one-hop step: the rows arrived at on one round
    are the rows departed from on the next, and every arrival at any
    depth is part of the answer. `upto any` repeats until a round adds
    nothing. Termination is free: the trail rule already forbids reusing
    an edge instance within a row, so a cycle runs out of unused edges.
    """
    if stmt.upto is None or stmt.upto == 1:
        _follow_once(stmt, table, store, schema)
        return

    import dataclasses

    reached: list[dict] = []
    frontier = list(table.rows)
    depth = 0
    while frontier:
        depth += 1
        hop_name = f"__upto{depth}"
        src = stmt.src if depth == 1 else f"__upto{depth - 1}"
        # Walk with no condition: a node that fails the filter is still a
        # route to nodes that pass it, so "cheap parts in this car" must
        # not stop at the expensive engine.
        step = Table(rows=frontier, seeded=True)
        _follow_once(
            dataclasses.replace(stmt, src=src, name=hop_name, cond=[], upto=None),
            step,
            store,
            schema,
        )
        if not step.rows:
            break
        frontier = step.rows
        for row in step.rows:
            dst = row[hop_name]
            if stmt.cond and not _eval_cond(
                store,
                schema,
                stmt.cond,
                lambda col, dst=dst: _first_prop(store, schema, dst, col),
            ):
                continue
            out = {k: v for k, v in row.items() if not k.startswith("__upto")}
            out[stmt.name] = dst
            out["__edges__"] = row.get("__edges__", ())
            reached.append(out)
        if stmt.upto and depth >= stmt.upto:
            break
    table.rows = reached


def _follow_once(stmt: Follow, table: Table, store: Store, schema: Schema) -> None:
    edef = schema.edges[stmt.edge]
    arrive_role = stmt.role
    depart_role = edef.other_role(arrive_role)
    new_rows = []
    touched: set[str] = set()
    for row in table.rows:
        src_id = store.resolve(row[stmt.src])
        matched = False
        for edge in store.edges.get(src_id, []):
            if edge.type != stmt.edge or edge.retired_at is not None:
                continue
            if store.resolve(edge.roles[depart_role]) != src_id:
                continue
            dst = store.resolve(edge.roles[arrive_role])
            dst_node = store.nodes.get(dst)
            if dst_node is None or dst_node.retired_at is not None:
                continue
            if not stmt.optional and edge.id in row.get("__edges__", ()):
                # Trail semantics: within one path an edge is walked once,
                # so "the other products using this part" excludes the one
                # you came from. An optional follow is a separate question
                # asked about each row, not a continuation of the path, so
                # the edge that reached the row is available to it again.
                continue
            if stmt.name in row and not _same_node(store, row[stmt.name], dst):
                continue  # the name is already bound: it must be this node
            if stmt.cond and not _eval_cond(
                store,
                schema,
                stmt.cond,
                lambda col, dst=dst, edge=edge: (
                    # via.<prop> asks about the relationship itself
                    edge.props.get(col[1])
                    if col[0] == "via"
                    else _first_prop(store, schema, dst, col)
                ),
            ):
                continue
            touched.add(src_id)
            touched.add(dst)
            matched = True
            new_rows.append(
                {
                    **row,
                    stmt.name: dst,
                    "__edges__": row.get("__edges__", ())
                    if stmt.optional
                    else (*row.get("__edges__", ()), edge.id),
                }
            )
        if stmt.optional and not matched:
            # "or none": the row survives with nothing bound to the name,
            # so counts over it come out as zero rather than the row
            # vanishing from the result entirely.
            new_rows.append({**row, stmt.name: None})
    for nid in touched:
        blob = 1 if store.nodes[nid].state == "blob" else 0
        store.apply({"op": "traffic", "id": nid, "n": 1, "blob": blob})
    table.rows = new_rows


def _group(stmt: GroupBy, table: Table, store: Store, schema: Schema) -> None:
    kind = "identity" if len(stmt.col) == 1 else "value"
    table.group_meta[stmt.name] = (stmt.col, kind)


def _scalar(v):
    return v if isinstance(v, (str, int, float, bool, type(None))) else repr(v)


def _return_key(
    store: Store, schema: Schema, row: dict, cols: list[Col], by_identity: bool = True
):
    """Identity of a row for the purpose of `return`.

    A column rooted at a node binding keys on that node's identity, so
    two different nodes that happen to share a name stay two rows. Any
    other column (a group key, an aggregate) keys on its value.
    """
    key = []
    for col in cols:
        held = row.get(col[0])
        if not by_identity:
            try:
                key.append(("value", _scalar(_col_value(store, schema, row, col))))
            except ExecError:
                key.append(("raw", _scalar(held)))
            continue
        if isinstance(held, str) and held in store.nodes:
            key.append(("node", store.resolve(held)))
            continue
        try:
            key.append(("value", _scalar(_col_value(store, schema, row, col))))
        except ExecError:
            key.append(("raw", _scalar(held)))
    return tuple(key)


def _distinct_rows(
    store: Store, schema: Schema, stmt: Return, rows: list[dict]
) -> list[dict]:
    """Collapse rows that answer the question the same way.

    `return` is set-valued: reaching one node by two paths answers the
    question once, not twice.
    """
    seen = set()
    out = []
    for row in rows:
        k = _return_key(store, schema, row, stmt.cols, not stmt.distinct)
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def _dedup(values: list) -> list:
    """Order-preserving dedup in linear time.

    Hashable values go through a set; unhashable ones (list-valued
    properties) fall back to a linear scan over just those. Equality
    semantics match a plain `in` test, since a set membership test still
    compares with == after the hash lookup.
    """
    seen: set = set()
    seen_unhashable: list = []
    out = []
    for v in values:
        try:
            if v in seen:
                continue
            seen.add(v)
        except TypeError:
            if v in seen_unhashable:
                continue
            seen_unhashable.append(v)
        out.append(v)
    return out


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
        raw = _dedup(raw)
    values = []
    for v in raw:
        if prop is not None and isinstance(v, str) and v in store.nodes:
            v = _node_value(store, schema, v, prop)
        values.append(v)
    values = [v for v in values if v is not None]
    table.rows = [{stmt.name: _agg_compute(stmt.op, values)}]
    table.group_meta.clear()


def _materialize_groups(
    gname: str, table: Table, store: Store, schema: Schema
) -> None:
    """Collapse the rows into one row per group key.

    Done on demand: by the first aggregate over the group, or by a return
    that names the group, so `group by x as g` then `return g.key` works
    without an aggregate in between.
    """
    if table.grouped or gname not in table.group_meta:
        return
    key_col, kind = table.group_meta[gname]
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
        base = {f"{gname}_key": key, f"__members_{gname}": groups[key]}
        if kind == "identity":
            base[key_col[0]] = key  # keep the node binding on the group row
        group_rows.append(base)
    table.rows = group_rows
    table.grouped = True


def _group_referenced_by(stmt: Return, table: Table) -> str | None:
    """The group a return asks to collapse, if any.

    Only naming the group itself or its key asks for one row per group.
    `g.<member>` names a binding through its group and reads as that
    binding, so it leaves the rows alone.
    """
    cols = list(stmt.cols) + ([stmt.order_by] if stmt.order_by else [])
    for col in cols:
        if col[0] in table.group_meta and (len(col) == 1 or col[1] == "key"):
            return col[0]
    return None


def _aggregate(stmt: Aggregate, table: Table, store: Store, schema: Schema) -> None:
    gname = stmt.col[0]
    if gname not in table.group_meta:
        _global_aggregate(stmt, table, store, schema)
        return
    member = stmt.col[1]
    prop = stmt.col[2] if len(stmt.col) > 2 else None
    key_col, kind = table.group_meta[gname]

    _materialize_groups(gname, table, store, schema)

    for row in table.rows:
        members = row[f"__members_{gname}"]
        raw = [m.get(member) for m in members]
        if stmt.distinct:
            raw = _dedup(raw)
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

    gname = _group_referenced_by(stmt, table)
    if gname is not None:
        _materialize_groups(gname, table, store, schema)
    rows = _distinct_rows(store, schema, stmt, table.rows)
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


class _Branches:
    """Collects the branches an `or` separates, and unions them.

    Statements after an `or` build a fresh table; the rows from earlier
    branches wait here until something that reads the whole result set
    (a group, an aggregate, a compute or the return) needs them.
    """

    def __init__(self) -> None:
        self.done: list[dict] = []
        self.any = False

    def split(self, table: Table) -> Table:
        self.done.extend(table.rows)
        self.any = True
        return Table()

    def flush(self, table: Table) -> None:
        if not self.any:
            return
        table.rows = self.done + table.rows
        table.seeded = True
        self.done = []
        self.any = False


BRANCH_STMTS = (Find, Follow)


def _apply_pipeline_stmt(stmt, table: Table, store: Store, schema: Schema) -> None:
    if isinstance(stmt, Find):
        found = _find_rows(stmt, store, schema)
        # A seeded-but-empty table means an earlier find matched zero rows;
        # the cross product must stay empty rather than restart from `found`.
        table.rows = _cross(table.rows, found, store) if table.seeded else found
        table.seeded = True
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
    branches = _Branches()
    output: list[str] = []
    for plan in plans:
        stmt = plan.stmt
        if isinstance(stmt, Or):
            table = branches.split(table)
            continue
        if not isinstance(stmt, BRANCH_STMTS):
            branches.flush(table)
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
    branches = _Branches()
    rows_out: list[list] = []
    for plan in plans:
        stmt = plan.stmt
        if isinstance(stmt, Or):
            table = branches.split(table)
            continue
        if not isinstance(stmt, BRANCH_STMTS):
            branches.flush(table)
        if isinstance(stmt, Return):
            gname = _group_referenced_by(stmt, table)
            if gname is not None:
                _materialize_groups(gname, table, store, schema)
            rows = _distinct_rows(store, schema, stmt, table.rows)
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


def _cross(
    rows_a: list[dict], rows_b: list[dict], store: Store | None = None
) -> list[dict]:
    """Combine two row sets, joining on any binding they share.

    Names the two sides have in common must denote the same node, so a
    shared name turns the cross product into a join. With no shared
    names this is the plain cross product it always was.
    """
    if not rows_a or not rows_b:
        return []
    shared = [k for k in rows_b[0] if k in rows_a[0] and k != "__edges__"]
    out = []
    for a in rows_a:
        for b in rows_b:
            if shared and any(
                _same_node(store, a.get(k), b.get(k)) is False for k in shared
            ):
                continue
            merged = {**a, **b}
            merged["__edges__"] = (
                *a.get("__edges__", ()),
                *b.get("__edges__", ()),
            )
            out.append(merged)
    return out


def _same_node(store: Store | None, x, y) -> bool:
    if store is not None and isinstance(x, str) and isinstance(y, str):
        if x in store.nodes and y in store.nodes:
            return store.resolve(x) == store.resolve(y)
    return x == y

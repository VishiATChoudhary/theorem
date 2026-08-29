"""Diagnostic: what would theorem score if `return` were set-valued?

theorem's tutorial tells the model "Results are sets: duplicates do not
matter", but neither `execute_rows` nor the rendering path deduplicates,
so a correct query like

    find flightaccident as fa
    follow fa departsFrom airport as a
    return a.name

emits one row per accident rather than one per airport. CypherBench gold
queries deduplicate (`WITH DISTINCT n RETURN n.name`), and the official
comparator rejects on row count before comparing, so those answers score
zero despite matching the intended set.

This runs the same plans and deduplicates rows on the bindings the
`return` columns reference, which is what `WITH DISTINCT n` does: two
genuinely distinct entities that share a name still produce two rows, as
the benchmark's own prompt requires. It changes nothing in the engine; it
measures how much of theorem's gap is this one mismatch.
"""

from __future__ import annotations

from theorem.ast_nodes import Return, SchemaStmt
from theorem.engine.executor import (
    Table,
    _apply_pipeline_stmt,
    _col_value,
    _sorted_rows,
)
from theorem.engine.storage import Store
from theorem.schema import Schema
from theorem.verifier import Plan

MAX_DEDUP_ROWS = 3_000_000


def _key(store: Store, schema: Schema, row: dict, bindings: list[str]):
    out = []
    for b in bindings:
        v = row.get(b)
        if isinstance(v, str) and v in store.nodes:
            v = store.resolve(v)  # node identity, not the name
        out.append(v if isinstance(v, (str, int, float, bool, type(None))) else repr(v))
    return tuple(out)


def execute_rows_setwise(
    plans: list[Plan], store: Store, schema: Schema
) -> list[list]:
    table = Table()
    rows_out: list[list] = []
    for plan in plans:
        stmt = plan.stmt
        if isinstance(stmt, Return):
            rows = table.rows
            bindings = []
            for col in stmt.cols:
                if col[0] not in bindings:
                    bindings.append(col[0])
            # Deduplicate before ordering and limiting, so "the tallest"
            # is chosen among distinct entities rather than among repeats.
            # Holding a key per row on top of the rows themselves was
            # enough to get the process OOM-killed on the widest movie
            # fanouts, so refuse rather than take the machine down; those
            # questions are already failures in the raw run too.
            if len(rows) > MAX_DEDUP_ROWS:
                raise MemoryError(
                    f"refusing to deduplicate {len(rows)} rows "
                    f"(limit {MAX_DEDUP_ROWS})"
                )
            seen = set()
            deduped = []
            for r in rows:
                k = _key(store, schema, r, bindings)
                if k in seen:
                    continue
                seen.add(k)
                deduped.append(r)
            rows = deduped
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

"""Session facade: the single entry point agents (and the eval harness) use.

run() takes a program, verifies it whole (nothing executes on any error),
then executes statement by statement: reads build a binding table, writes
return receipts.

Binding lifetime: within one run() call, all bindings flow freely. Across
calls, bindings stay usable as WRITE arguments (merge, retire, compact,
edge roles) because the session keeps their node ids, but a read pipeline
(follow, group, aggregate, return) must re-find them: the binding table
is per-call, and the verifier rejects stale read references explicitly
instead of executing against an empty table.
"""

from __future__ import annotations

from pathlib import Path

from .ast_nodes import (
    Aggregate,
    Compute,
    Continue,
    Find,
    Follow,
    GroupBy,
    Return,
    SchemaStmt,
)
from .engine.executor import ExecError, ReadContext, Table, execute_read
from .engine.storage import Store
from .engine.writes import WriteContext, WriteError, execute_write
from .parser import ParseError, parse
from .schema import Schema
from .verifier import VerifyError, verify

READ_STMTS = (Find, Follow, GroupBy, Aggregate, Compute, Return, Continue, SchemaStmt)


class Session:
    def __init__(self, path: str | Path, schema: Schema):
        self.store = Store(path)
        self.schema = schema
        self._restore_derived_schema()
        self.read_ctx = ReadContext()
        self.write_ctx = WriteContext(store=self.store, schema=schema)
        self.type_env: dict[str, str] = {}

    def _restore_derived_schema(self) -> None:
        """derive class/edge are durable via their lineage records; rebuild
        the schema entries a previous process created, or restarts orphan
        their data."""
        from .schema import ClassDef, EdgeDef

        for rec in self.store.lineage:
            kind = rec.get("kind")
            if kind == "derive_class":
                name = rec["child"]
                if name in self.schema.classes:
                    continue
                self.schema.classes[name] = ClassDef(
                    name=name,
                    props=dict(rec.get("props", {})),
                    base=rec.get("parent"),
                    status="provisional",
                    quota=rec.get("quota", 500),
                    dedup_threshold=rec.get("dedup"),
                )
            elif kind == "derive_edge":
                self.schema.edges.setdefault(
                    rec["name"], EdgeDef(rec["name"], dict(rec["roles"]))
                )
            elif kind == "deprecate_class":
                name = rec["name"]
                if name in self.schema.classes:
                    self.schema.classes[name].status = "deprecated"

    def run(self, text: str) -> str:
        try:
            stmts = parse(text)
            stale_env = {
                name: typ if typ.startswith("prior:") else f"prior:{typ}"
                for name, typ in self.type_env.items()
            }
            plans = verify(stmts, self.schema, stale_env)
        except ParseError as e:
            return f"error: {e}\nnothing was executed."
        except VerifyError as e:
            return str(e)

        outputs: list[str] = []
        table = Table()
        read_batch = []
        try:
            for plan in plans:
                if isinstance(plan.stmt, READ_STMTS):
                    read_batch.append(plan)
                    if isinstance(plan.stmt, (Return, Continue, SchemaStmt)):
                        outputs.append(
                            execute_read(
                                read_batch,
                                self.store,
                                self.schema,
                                self.read_ctx,
                                table,
                            )
                        )
                        read_batch = []
                        # a return closes the pipeline; the next batch's
                        # first find reseeds instead of crossing with an
                        # empty (or stale) table
                        table.seeded = False
                else:
                    if read_batch:
                        execute_read(
                            read_batch, self.store, self.schema, self.read_ctx, table
                        )
                        read_batch = []
                    self._export_bindings(table)
                    receipt = execute_write(plan.stmt, self.write_ctx)
                    outputs.append(receipt.render())
                self.type_env = plan.binding_types
            if read_batch:
                outputs.append(
                    execute_read(
                        read_batch, self.store, self.schema, self.read_ctx, table
                    )
                )
        except (ExecError, WriteError) as e:
            outputs.append(f"error: {e}")
        except Exception as e:  # the REPL/agent contract is
            # that run() always returns a message, never a raw traceback
            outputs.append(f"internal error: {type(e).__name__}: {e}")
        self._export_bindings(table)
        return "\n".join(o for o in outputs if o)

    def _export_bindings(self, table: Table) -> None:
        """Make read-bound node sets available to write verbs (compact, merge)."""
        cols: dict[str, list] = {}
        for row in table.rows:
            for key, value in row.items():
                if key.startswith("__"):
                    continue
                if isinstance(value, str) and value in self.store.nodes:
                    cols.setdefault(key, [])
                    if value not in cols[key]:
                        cols[key].append(value)
        for name, ids in cols.items():
            self.write_ctx.env[name] = ids

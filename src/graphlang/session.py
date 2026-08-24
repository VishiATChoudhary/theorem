"""Session facade: the single entry point agents (and the eval harness) use.

run() takes a program, verifies it whole (nothing executes on any error),
then executes statement by statement: reads build a binding table, writes
return receipts. Bindings persist across run() calls.
"""

from __future__ import annotations

from pathlib import Path

from .ast_nodes import (
    Aggregate,
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

READ_STMTS = (Find, Follow, GroupBy, Aggregate, Return, Continue, SchemaStmt)


class Session:
    def __init__(self, path: str | Path, schema: Schema):
        self.store = Store(path)
        self.schema = schema
        self.read_ctx = ReadContext()
        self.write_ctx = WriteContext(store=self.store, schema=schema)
        self.type_env: dict[str, str] = {}

    def run(self, text: str) -> str:
        try:
            stmts = parse(text)
            plans = verify(stmts, self.schema, self.type_env)
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
                        outputs.append(execute_read(
                            read_batch, self.store, self.schema,
                            self.read_ctx, table))
                        read_batch = []
                else:
                    if read_batch:
                        execute_read(read_batch, self.store, self.schema,
                                     self.read_ctx, table)
                        read_batch = []
                    self._export_bindings(table)
                    receipt = execute_write(plan.stmt, self.write_ctx)
                    outputs.append(receipt.render())
                self.type_env = plan.binding_types
            if read_batch:
                outputs.append(execute_read(read_batch, self.store, self.schema,
                                            self.read_ctx, table))
        except (ExecError, WriteError) as e:
            outputs.append(f"error: {e}")
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

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
    Keep,
    Or,
    Return,
    SchemaStmt,
)
from .engine.executor import ExecError, ReadContext, Table, execute_read
from .engine.storage import Store
from .engine.writes import WriteContext, WriteError, execute_write
from .parser import ParseError, parse
from .schema import Schema
from .verifier import VerifyError, verify

# Every statement a read pipeline can contain. A verb missing from here
# is routed to the write path, which rejects it: `or` and `keep` shipped
# that way and were reachable only by calling the executor directly.
READ_STMTS = (
    Find,
    Follow,
    GroupBy,
    Aggregate,
    Keep,
    Compute,
    Or,
    Return,
    Continue,
    SchemaStmt,
)


def _partial(committed: int, *, receipts: bool = False) -> str:
    """How much of a failed program stuck, as a leading-newline suffix.

    Verification is all or nothing; execution is not. Saying so is the
    difference between a caller retrying the whole program and a caller
    retrying the rest of it, and it is the one fact an exception has to
    carry that a rendered error carries in its text.
    """
    if not committed:
        return ""
    plural = "s" if committed > 1 else ""
    above = " their receipts are above." if receipts else ""
    joiner = ";" if receipts else "."
    return (
        f"\n{committed} write{plural} before this one committed{joiner}{above} "
        "The rest of the program did not run."
    )


class Session:
    def __init__(self, path: str | Path, schema: Schema, *, lock: bool = True):
        self.store = Store(path, lock=lock)
        self.schema = schema
        self._restore_derived_schema()
        self.read_ctx = ReadContext()
        self.write_ctx = WriteContext(store=self.store, schema=schema)
        self.type_env: dict[str, str] = {}

    def close(self) -> None:
        """Release the store directory so another process can write it."""
        self.store.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

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

        # The "playbook" tag on a derive_class/derive_edge record is set by
        # mutating the in-memory lineage dict at apply time and is never
        # itself written to the WAL; only the separate playbook_link record
        # (kind, playbook, names) is durable. Re-derive the tag from those
        # links so a restart doesn't silently drop playbook ownership.
        playbook_by_name: dict[str, str] = {}
        for rec in self.store.lineage:
            if rec.get("kind") == "playbook_link":
                for name in rec.get("names", []):
                    playbook_by_name[name] = rec["playbook"]
        for rec in self.store.lineage:
            kind = rec.get("kind")
            if kind not in ("derive_class", "derive_edge") or "playbook" in rec:
                continue
            name = rec["child"] if kind == "derive_class" else rec["name"]
            if name in playbook_by_name:
                rec["playbook"] = playbook_by_name[name]

    def rows(self, text: str) -> list[list]:
        """Run a read program and return its rows as plain values.

        `run` renders an answer for a reader, which is what an agent
        wants and what a program has to parse back out again. This is the
        same pipeline without the rendering, and it raises rather than
        returning an error as text, because a caller in code has
        `except` and does not have to remember to look.
        """
        from .engine.executor import execute_rows

        plans = verify(parse(text), self.schema)
        for plan in plans:
            if not isinstance(plan.stmt, READ_STMTS):
                raise WriteError(
                    f"rows() runs reads; {type(plan.stmt).__name__} is a write. "
                    "Use run() for writes, which returns their receipt."
                )
        if not any(isinstance(p.stmt, Return) for p in plans):
            # Without this, a program that forgot its `return`, or an empty
            # one, comes back as a successful answer of no rows, which is
            # indistinguishable from a true empty answer. That is the exact
            # failure the language exists to remove.
            raise ExecError(
                "this program asks for nothing: a read ends with "
                "`return <col>, ...` naming the properties you want."
                if plans
                else "there is no query here."
            )
        return execute_rows(plans, self.store, self.schema)

    def run(self, text: str) -> str:
        """Run a program and render the result, errors included, as text.

        This is the agent contract: a model that made a mistake gets the
        corrective message back verbatim and tries again, so a failure is
        a string rather than an exception. Code embedding theorem wants
        the opposite and should call `execute` or `rows`.
        """
        return self._execute(text, strict=False)

    def execute(self, text: str) -> str:
        """Run a program and raise if any part of it fails.

        Same pipeline as `run`, for callers that are programs rather than
        models: an error is raised instead of returned as text, so a
        caller cannot mistake a failure for an answer by forgetting to
        read one. Reads and writes are both allowed, which is what
        separates this from `rows`.
        """
        return self._execute(text, strict=True)

    def _execute(self, text: str, *, strict: bool) -> str:
        try:
            stmts = parse(text)
            stale_env = {
                name: typ if typ.startswith("prior:") else f"prior:{typ}"
                for name, typ in self.type_env.items()
            }
            plans = verify(stmts, self.schema, stale_env)
        except ParseError as e:
            if strict:
                raise
            return f"error: {e}\nnothing was executed."
        except VerifyError as e:
            if strict:
                raise
            return str(e)

        outputs: list[str] = []
        table = Table()
        read_batch = []
        committed = 0
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
                    committed += 1
                self.type_env = plan.binding_types
            if read_batch:
                outputs.append(
                    execute_read(
                        read_batch, self.store, self.schema, self.read_ctx, table
                    )
                )
        except (ExecError, WriteError) as e:
            if strict:
                # The same fact the message below carries, on the exception,
                # because a caller in code has no message to read.
                self._export_bindings(table)
                raise type(e)(f"{e}{_partial(committed)}") from e
            outputs.append(f"error: {e}")
            outputs.append(_partial(committed, receipts=True).lstrip())
        except Exception as e:  # the REPL/agent contract is
            # that run() always returns a message, never a raw traceback
            if strict:
                self._export_bindings(table)
                raise
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

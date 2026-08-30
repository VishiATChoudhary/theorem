"""Deterministic bulk load of CSV and JSONL into an existing schema.

The document pipeline in this package stages a file as a blob and has an
agent extract from it, which is the right shape for a PDF and the wrong
one for a million rows whose columns are already known: it is slow, it
costs a model call, and it does not give the same answer twice. This
module is the other case. It writes what the file says, coerced to the
types the schema declares, and it refuses anything it cannot place.

Guards that exist for an agent writing one node at a time are not run
here: no dedup pass and no provisional quota. A bulk load is an operator
saying "this file is the truth", and checking a million rows against each
other is a different (quadratic) job. `theorem`'s dedup sweep can run
afterwards.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..engine.text import fold


class LoadError(Exception):
    """The file cannot be placed in the schema. Nothing was written."""


@dataclass
class LoadReceipt:
    kind: str
    name: str
    rows: int = 0
    written: int = 0
    skipped: list[str] = field(default_factory=list)

    def render(self) -> str:
        out = [f"receipt: loaded {self.written} {self.kind}s into {self.name}"]
        if self.rows != self.written:
            out.append(f"  {self.rows - self.written} of {self.rows} rows skipped")
        for note in self.skipped[:5]:
            out.append(f"  {note}")
        if len(self.skipped) > 5:
            out.append(f"  ... and {len(self.skipped) - 5} more")
        return "\n".join(out)


def read_rows(path: Path) -> list[dict]:
    """CSV or JSONL, decided by the file's own shape, not its name."""
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return []
    if path.suffix.lower() in (".jsonl", ".ndjson") or text.lstrip()[0] == "{":
        rows = []
        for i, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise LoadError(f"{path.name} line {i} is not JSON: {e}") from e
            if not isinstance(rec, dict):
                raise LoadError(f"{path.name} line {i} is not an object")
            rows.append(rec)
        return rows
    return list(csv.DictReader(io.StringIO(text)))


def coerce(value, typ: str, column: str, line: int):
    """A value from a text file, as the type the schema declares."""
    if value is None or value == "":
        return None
    if typ == "str":
        return str(value)
    if typ == "bool":
        if isinstance(value, bool):
            return value
        if str(value).strip().lower() in ("true", "1", "yes", "t"):
            return True
        if str(value).strip().lower() in ("false", "0", "no", "f"):
            return False
        raise LoadError(f"line {line}: {column}={value!r} is not a bool")
    try:
        return int(value) if typ == "int" else float(value)
    except (TypeError, ValueError) as e:
        raise LoadError(f"line {line}: {column}={value!r} is not {typ}") from e


def load_nodes(session, path: Path, cls: str) -> LoadReceipt:
    """One node per row. Columns must be properties the class declares."""
    schema = session.schema
    if cls not in schema.classes:
        raise LoadError(
            f"unknown class {cls!r}. known: {', '.join(sorted(schema.classes))}. "
            "Declare it first with `derive class`."
        )
    props = schema.classes[cls].props
    rows = read_rows(path)
    if not rows:
        return LoadReceipt("node", cls)
    unknown = [c for c in rows[0] if c not in props]
    if unknown:
        raise LoadError(
            f"{path.name} has columns {cls} does not declare: "
            f"{', '.join(sorted(unknown))}. Declared: {', '.join(sorted(props))}. "
            "Nothing was written."
        )

    store = session.store
    records = []
    for line, row in enumerate(rows, 2):
        values = {}
        for column, raw in row.items():
            value = coerce(raw, props[column], column, line)
            if value is not None:
                values[column] = value
        records.append(
            {
                "op": "put_node",
                "id": store.next_id(cls),
                "cls": cls,
                "props": values,
            }
        )
    store.bulk(records)
    return LoadReceipt("node", cls, rows=len(rows), written=len(records))


def _endpoint(store, schema, cls: str, value: str, line: int) -> str:
    """A node id, from an id or from a name.

    Naming a node by its name is what a spreadsheet actually holds, and
    the store already indexes names per class, so it costs a lookup. Two
    nodes sharing a name is an error rather than a coin flip.
    """
    if isinstance(value, str) and value.startswith("#"):
        resolved = store.resolve(value)
        if resolved not in store.nodes:
            raise LoadError(f"line {line}: no node {value}")
        return resolved
    ids = store.by_name.get((cls, fold(value)), [])
    if not ids:
        raise LoadError(f"line {line}: no {cls} named {value!r}")
    if len({store.resolve(i) for i in ids}) > 1:
        raise LoadError(
            f"line {line}: {len(ids)} {cls}s are named {value!r}. "
            "Reference them by id, or merge them first."
        )
    return store.resolve(ids[0])


def load_edges(session, path: Path, edge: str, columns: dict[str, str]) -> LoadReceipt:
    """One edge per row. `columns` maps each role to the column naming it."""
    schema = session.schema
    if edge not in schema.edges:
        raise LoadError(
            f"unknown edge {edge!r}. known: {', '.join(sorted(schema.edges))}. "
            "Declare it first with `derive edge`."
        )
    edef = schema.edges[edge]
    missing = set(edef.roles) - set(columns)
    if missing:
        raise LoadError(
            f"edge {edge} has roles {', '.join(sorted(edef.roles))}; "
            f"no column was given for {', '.join(sorted(missing))}."
        )
    extra = set(columns) - set(edef.roles)
    if extra:
        raise LoadError(f"edge {edge} has no role {', '.join(sorted(extra))}")

    rows = read_rows(path)
    if not rows:
        return LoadReceipt("edge", edge)
    for role, column in columns.items():
        if column not in rows[0]:
            raise LoadError(f"{path.name} has no column {column!r} for role {role}")

    store = session.store
    records, skipped = [], []
    for line, row in enumerate(rows, 2):
        try:
            roles = {
                role: _endpoint(store, schema, edef.roles[role], row[column], line)
                for role, column in columns.items()
            }
        except LoadError as e:
            skipped.append(str(e))
            continue
        props = {
            k: v
            for k, v in row.items()
            if k not in columns.values() and k in edef.props and v not in (None, "")
        }
        for k in list(props):
            props[k] = coerce(props[k], edef.props[k], k, line)
        records.append(
            {
                "op": "put_edge",
                "id": store.next_id("edge"),
                "type": edge,
                "roles": roles,
                "props": props,
            }
        )
    if records:
        store.bulk(records)
    return LoadReceipt("edge", edge, len(rows), len(records), skipped)

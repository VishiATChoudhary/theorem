"""Single-process store with the disaggregated shape preserved.

Durable truth = append-only WAL (wal.jsonl) + immutable snapshot runs
(runs/run-<pos>.json). In-memory state is rebuilt by replaying the newest
run then the WAL. Records are pure data; all interpretation lives here so
replay and live application share one code path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class StoreError(Exception):
    """Durable-state problem: corrupt WAL/run file or invalid record."""


@dataclass
class Node:
    id: str
    cls: str
    props: dict[str, object]
    state: str = "atom"
    created_at: int = 0
    retired_at: int | None = None
    origin: str | None = None  # lineage parent node id (refine)
    flags: list[str] = field(default_factory=list)
    traffic: int = 0  # traversals through this node (query_traffic)
    blob_traversals: int = 0  # traversals into blob payload
    conflict_count: int = 0  # conflicting re-asserts of same property
    last_confirmed: int = 0  # position of last confirming write


@dataclass
class Edge:
    id: str
    type: str
    roles: dict[str, str]  # role name -> node id
    created_at: int = 0
    retired_at: int | None = None


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "runs").mkdir(exist_ok=True)
        self.wal_path = self.path / "wal.jsonl"
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, list[Edge]] = {}
        self.edge_index: dict[str, Edge] = {}
        self.lineage: list[dict] = []
        self.distinct_pairs: set[frozenset] = set()
        self.dup_ledger: list[dict] = []
        self.aliases: dict[str, str] = {}
        self.id_counters: dict[str, int] = {}
        self.position = 0
        self._replay()

    # ---- durability ------------------------------------------------

    def _replay(self) -> None:
        runs = sorted(
            self.path.glob("runs/run-*.json"), key=lambda p: int(p.stem.split("-")[1])
        )
        if runs:
            try:
                data = json.loads(runs[-1].read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise StoreError(
                    f"corrupt run file {runs[-1].name}: {e}. "
                    "The file was likely torn by a crash mid-snapshot; "
                    "remove it to fall back to the previous run + WAL."
                ) from e
            self.position = data["position"]
            self.id_counters = data["id_counters"]
            for rec in data["records"]:
                self._apply_to_memory(rec, rec["_pos"])
        base = self.position  # records at or below this are in the snapshot
        if self.wal_path.exists():
            # Parse every line first. A single invalid line is only
            # recoverable when it is the torn TAIL of the file (crash
            # mid-append); an invalid line followed by valid records means
            # real corruption, and truncating would delete committed data.
            raw_lines = self.wal_path.read_bytes().splitlines(keepends=True)
            parsed: list[dict | None] = []
            for line in raw_lines:
                if not line.endswith(b"\n"):
                    parsed.append(None)
                    continue
                try:
                    parsed.append(json.loads(line))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    parsed.append(None)
            if None in parsed:
                first_bad = parsed.index(None)
                if any(p is not None for p in parsed[first_bad + 1 :]):
                    raise StoreError(
                        f"corrupt WAL: line {first_bad + 1} of "
                        f"{self.wal_path} is unreadable but valid records "
                        "follow it. Refusing to truncate; repair manually."
                    )
                # torn tail: drop it and truncate to the valid prefix
                valid_bytes = sum(len(line) for line in raw_lines[:first_bad])
                parsed = parsed[:first_bad]
                with self.wal_path.open("r+b") as f:
                    f.truncate(valid_bytes)
            for rec in parsed:
                # If a crash hit between snapshot() writing the run file and
                # truncating the WAL, WAL records are already baked into the
                # run; their recorded _pos tells us to skip them.
                rec_pos = rec.get("_pos")
                if rec_pos is not None and rec_pos <= base:
                    continue
                self.position += 1
                self._apply_to_memory(rec, self.position)

    def _validate(self, record: dict) -> None:
        """Reject records that would poison the WAL: they must be appliable."""
        op = record.get("op")
        if op in ("patch_node", "retire", "flag", "traffic"):
            if record.get("id") not in self.nodes:
                raise StoreError(f"{op}: unknown node {record.get('id')!r}")
        elif op == "retire_edge":
            if record.get("id") not in self.edge_index:
                raise StoreError(f"retire_edge: unknown edge {record.get('id')!r}")
        elif op == "put_node":
            if not isinstance(record.get("props"), dict):
                raise StoreError("put_node: props must be an object")

    def apply(self, record: dict) -> int:
        """Append to WAL, apply to memory, return the new position."""
        self._validate(record)
        record = {**record, "_pos": self.position + 1}
        with self.wal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        self.position += 1
        self._apply_to_memory(record, self.position)
        return self.position

    def bulk(self, records: list[dict]) -> int:
        """Append many records in one WAL write. Returns the final position."""
        with self.wal_path.open("a", encoding="utf-8") as f:
            for record in records:
                self._validate(record)
                record = {**record, "_pos": self.position + 1}
                f.write(json.dumps(record) + "\n")
                self.position += 1
                self._apply_to_memory(record, self.position)
        return self.position

    def wal_len(self) -> int:
        if not self.wal_path.exists():
            return 0
        return sum(1 for _ in self.wal_path.open())

    def snapshot(self) -> Path:
        """Write an immutable run holding the full replayable state, truncate WAL."""
        records = []
        for n in self.nodes.values():
            records.append(
                {
                    "op": "put_node",
                    "id": n.id,
                    "cls": n.cls,
                    "props": n.props,
                    "state": n.state,
                    "origin": n.origin,
                    "_pos": n.created_at,
                    "_restore": {
                        "retired_at": n.retired_at,
                        "flags": n.flags,
                        "traffic": n.traffic,
                        "blob_traversals": n.blob_traversals,
                        "conflict_count": n.conflict_count,
                        "last_confirmed": n.last_confirmed,
                    },
                }
            )
        for e in self.edge_index.values():
            records.append(
                {
                    "op": "put_edge",
                    "id": e.id,
                    "type": e.type,
                    "roles": e.roles,
                    "_pos": e.created_at,
                    "_restore": {"retired_at": e.retired_at},
                }
            )
        for rec in self.lineage:
            records.append({**rec, "op": "lineage", "_pos": rec.get("_pos", 0)})
        for pair in self.distinct_pairs:
            if len(pair) != 2:  # defensive: self-pairs collapse to one element
                continue
            a, b = sorted(pair)
            records.append({"op": "distinct", "a": a, "b": b, "reason": "", "_pos": 0})
        for rec in self.dup_ledger:
            records.append({**rec, "op": "dup", "_pos": rec.get("_pos", 0)})
        for absorbed, survivor in self.aliases.items():
            records.append(
                {"op": "alias", "absorbed": absorbed, "survivor": survivor, "_pos": 0}
            )
        run_path = self.path / "runs" / f"run-{self.position}.json"
        # write-then-rename so a crash mid-write never leaves a torn run file
        tmp_path = run_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(
                {
                    "position": self.position,
                    "id_counters": self.id_counters,
                    "records": records,
                }
            ),
            encoding="utf-8",
        )
        tmp_path.rename(run_path)
        self.wal_path.write_text("")
        return run_path

    # ---- ids -------------------------------------------------------

    def next_id(self, cls: str) -> str:
        prefix = cls[0]
        n = self.id_counters.get(prefix, 0) + 1
        self.id_counters[prefix] = n
        return f"#{prefix}-{n}"

    def _bump_counter(self, cls: str, node_id: str) -> None:
        """Keep id counters ahead of every replayed id so ids never collide."""
        prefix = cls[0]
        suffix = node_id.rsplit("-", 1)[-1]
        if suffix.isdigit():
            self.id_counters[prefix] = max(self.id_counters.get(prefix, 0), int(suffix))

    def resolve(self, node_id: str) -> str:
        seen = set()
        while node_id in self.aliases and node_id not in seen:
            seen.add(node_id)
            node_id = self.aliases[node_id]
        return node_id

    # ---- record application ---------------------------------------

    def _apply_to_memory(self, rec: dict, pos: int) -> None:
        op = rec["op"]
        # Replay resilience: a record referencing a node/edge that never
        # materialized (partial multi-record write before a crash) is
        # skipped rather than crashing the constructor. Live writes are
        # validated up front in apply(), so this only fires during replay.
        if (
            op in ("patch_node", "retire", "flag", "traffic")
            and rec.get("id") not in self.nodes
        ):
            return
        if op == "retire_edge" and rec.get("id") not in self.edge_index:
            return
        if op == "put_node":
            node = Node(
                id=rec["id"],
                cls=rec["cls"],
                props=dict(rec["props"]),
                state=rec.get("state", "atom"),
                created_at=pos,
                origin=rec.get("origin"),
            )
            node.last_confirmed = pos
            for k, v in rec.get("_restore", {}).items():
                setattr(node, k, v)
            self.nodes[node.id] = node
            self.edges.setdefault(node.id, [])
            self._bump_counter(node.cls, node.id)
        elif op == "patch_node":
            node = self.nodes[rec["id"]]
            for k, v in rec["props"].items():
                if k in node.props and node.props[k] != v:
                    node.conflict_count += 1
                node.props[k] = v
            node.last_confirmed = pos
            if "state" in rec:
                node.state = rec["state"]
        elif op == "put_edge":
            edge = Edge(
                id=rec["id"], type=rec["type"], roles=dict(rec["roles"]), created_at=pos
            )
            for k, v in rec.get("_restore", {}).items():
                setattr(edge, k, v)
            self.edge_index[edge.id] = edge
            self._bump_counter("edge", edge.id)
            for nid in edge.roles.values():
                self.edges.setdefault(nid, []).append(edge)
        elif op == "retire":
            node = self.nodes[rec["id"]]
            node.retired_at = pos
            node.props["_retire_reason"] = rec.get("reason", "")
        elif op == "retire_edge":
            self.edge_index[rec["id"]].retired_at = pos
        elif op == "alias":
            self.aliases[rec["absorbed"]] = rec["survivor"]
        elif op == "lineage":
            self.lineage.append({**rec, "_pos": pos})
        elif op == "distinct":
            self.distinct_pairs.add(frozenset((rec["a"], rec["b"])))
        elif op == "dup":
            pair = frozenset((rec["a"], rec["b"]))
            if pair not in self.distinct_pairs:
                self.dup_ledger.append({**rec, "_pos": pos})
        elif op == "flag":
            node = self.nodes[rec["id"]]
            node.flags.append(rec.get("reason", ""))
        elif op == "traffic":
            node = self.nodes[rec["id"]]
            node.traffic += rec.get("n", 1)
            node.blob_traversals += rec.get("blob", 0)
        else:
            raise ValueError(f"unknown WAL op {op!r}")

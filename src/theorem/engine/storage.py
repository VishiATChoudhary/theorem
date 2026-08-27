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
            data = json.loads(runs[-1].read_text())
            self.position = data["position"]
            self.id_counters = data["id_counters"]
            for rec in data["records"]:
                self._apply_to_memory(rec, rec["_pos"])
        if self.wal_path.exists():
            # A crash mid-append leaves a torn final line. Replay the longest
            # valid prefix, then truncate the file to it so the next append
            # starts on a clean line boundary.
            valid_bytes = 0
            with self.wal_path.open("rb") as f:
                for line in f:
                    if not line.endswith(b"\n"):
                        break
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        break
                    self.position += 1
                    self._apply_to_memory(rec, self.position)
                    valid_bytes += len(line)
            if valid_bytes < self.wal_path.stat().st_size:
                with self.wal_path.open("r+b") as f:
                    f.truncate(valid_bytes)

    def apply(self, record: dict) -> int:
        """Append to WAL, apply to memory, return the new position."""
        with self.wal_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        self.position += 1
        self._apply_to_memory(record, self.position)
        return self.position

    def bulk(self, records: list[dict]) -> int:
        """Append many records in one WAL write. Returns the final position."""
        with self.wal_path.open("a") as f:
            for record in records:
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
            a, b = sorted(pair)
            records.append({"op": "distinct", "a": a, "b": b, "reason": "", "_pos": 0})
        for rec in self.dup_ledger:
            records.append({**rec, "op": "dup", "_pos": rec.get("_pos", 0)})
        for absorbed, survivor in self.aliases.items():
            records.append(
                {"op": "alias", "absorbed": absorbed, "survivor": survivor, "_pos": 0}
            )
        run_path = self.path / "runs" / f"run-{self.position}.json"
        run_path.write_text(
            json.dumps(
                {
                    "position": self.position,
                    "id_counters": self.id_counters,
                    "records": records,
                }
            )
        )
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

"""Single-process store with the disaggregated shape preserved.

Durable truth = append-only WAL (wal.jsonl) + immutable snapshot runs
(runs/run-<pos>.json). In-memory state is rebuilt by replaying the newest
run then the WAL. Records are pure data; all interpretation lives here so
replay and live application share one code path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # POSIX
    import fcntl

    msvcrt = None
except ImportError:  # Windows
    fcntl = None
    import msvcrt

# Windows locks a byte range from the current file position, so the lock
# byte sits past anything the file actually holds; the holder's pid, at
# offset zero, stays readable by the process that was refused.
_LOCK_BYTE = 1 << 20


class StoreError(Exception):
    """Durable-state problem: corrupt WAL/run file or invalid record."""


class StoreLocked(StoreError):
    """Another writer already holds this store directory."""


def _lock(f) -> None:
    """Take an exclusive advisory lock, or raise OSError. Never blocks."""
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        f.seek(_LOCK_BYTE)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)


def _unlock(f) -> None:
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_UN)
    else:
        f.seek(_LOCK_BYTE)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


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
    props: dict[str, object] = field(default_factory=dict)
    created_at: int = 0
    retired_at: int | None = None


class Store:
    """One writer per directory.

    `snapshot_every` is the number of WAL records after which the store
    compacts itself: without it the WAL grows for the life of the graph
    and every startup replays the whole history. The default is high
    enough that a small store never pays for a snapshot it does not need.

    `lock=False` is for a tool that only reads a directory nobody is
    writing. Two writers is the case this class exists to prevent.

    Durability: a committed record survives the process dying, because
    the WAL write has reached the operating system. It does not survive
    the machine losing power, because nothing is fsynced on the write
    path. Snapshots are fsynced, being rare.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        lock: bool = True,
        snapshot_every: int = 50_000,
        keep_runs: int = 2,
    ):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "runs").mkdir(exist_ok=True)
        self.wal_path = self.path / "wal.jsonl"
        self.snapshot_every = snapshot_every
        self.keep_runs = keep_runs
        self._pid = os.getpid()
        self._lock_file = None
        self._wal_records = 0
        self._loaded_run: Path | None = None
        if lock:
            self._acquire_lock()
        self.nodes: dict[str, Node] = {}
        # class name -> node ids, so seeding a query costs the class
        # rather than the whole store
        self.by_class: dict[str, list[str]] = {}
        # (class, folded name) -> node ids, so looking a node up by name
        # costs the name rather than the class
        self.by_name: dict[tuple[str, str], list[str]] = {}
        self.edges: dict[str, list[Edge]] = {}
        self.edge_index: dict[str, Edge] = {}
        self.lineage: list[dict] = []
        self.distinct_pairs: set[frozenset] = set()
        self.dup_ledger: list[dict] = []
        self.aliases: dict[str, str] = {}
        self.id_counters: dict[str, int] = {}
        self.position = 0
        try:
            self._replay()
        except Exception:
            self.close()
            raise

    # ---- one writer --------------------------------------------------

    def _acquire_lock(self) -> None:
        """Take the directory, or say who has it.

        The lock is an advisory `flock`, which the operating system drops
        when the holding process dies however it dies. A crashed writer
        therefore does not leave the directory unopenable, which a lock
        made of a file's existence would.
        """
        lock_path = self.path / "lock"
        f = lock_path.open("a+", encoding="utf-8")
        try:
            _lock(f)
        except OSError as e:
            f.seek(0)
            holder = f.read().strip() or "unknown"
            f.close()
            raise StoreLocked(
                f"{self.path} is open for writing by process {holder}. "
                "A store takes one writer at a time; two would each assign "
                "the same ids and overwrite each other's records. Close the "
                "other writer, or open this one with lock=False if you only "
                "intend to read."
            ) from e
        f.seek(0)
        f.truncate()
        f.write(str(self._pid))
        f.flush()
        self._lock_file = f

    def close(self) -> None:
        """Release the directory. Safe to call twice."""
        if self._lock_file is not None:
            try:
                _unlock(self._lock_file)
            except OSError:
                pass  # closing the file releases it regardless
            finally:
                self._lock_file.close()
                self._lock_file = None

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        # A dropped Store should not keep the directory hostage for the
        # life of the process. The OS would release it at exit anyway.
        try:
            self.close()
        except Exception:
            pass

    # ---- durability ------------------------------------------------

    def _replay(self) -> None:
        runs = sorted(
            self.path.glob("runs/run-*.json"), key=lambda p: int(p.stem.split("-")[1])
        )
        self._loaded_run = runs[-1] if runs else None
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
                self._wal_records += 1
                rec_pos = rec.get("_pos")
                if rec_pos is not None and rec_pos <= base:
                    continue
                self.position += 1
                self._apply_to_memory(rec, self.position)

    def refresh(self) -> int:
        """Catch up with whatever a writer has committed since.

        A store reads its directory once, at open, so a second process
        holding it open for reads answers from the graph as it was. This
        replays what has been appended since, and returns how many
        records that was.

        Records are selected by the position they carry rather than by a
        byte offset, so a writer that compacted the log mid-read is not a
        special case: the run file is simply newer, and the whole store is
        rebuilt from it. Correctness here is worth more than the read it
        costs, since the alternative is silently answering from a graph
        that no longer exists.
        """
        newest = self._newest_run()
        if newest != self._loaded_run:
            before = self.position
            self._reset()
            self._replay()
            return max(0, self.position - before)
        if not self.wal_path.exists():
            return 0
        applied = 0
        for line in self.wal_path.read_bytes().splitlines(keepends=True):
            if not line.endswith(b"\n"):
                break  # a torn tail: the writer is mid-append, come back later
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                break
            if (rec.get("_pos") or 0) <= self.position:
                continue
            self.position += 1
            self._wal_records += 1
            self._apply_to_memory(rec, self.position)
            applied += 1
        return applied

    def _newest_run(self) -> Path | None:
        runs = sorted(
            self.path.glob("runs/run-*.json"), key=lambda p: int(p.stem.split("-")[1])
        )
        return runs[-1] if runs else None

    def _reset(self) -> None:
        """Drop everything derived from the log, keeping the file handles."""
        self.nodes = {}
        self.by_class = {}
        self.by_name = {}
        self.edges = {}
        self.edge_index = {}
        self.lineage = []
        self.distinct_pairs = set()
        self.dup_ledger = []
        self.aliases = {}
        self.id_counters = {}
        self.position = 0
        self._wal_records = 0

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
        self._wal_records += 1
        self._apply_to_memory(record, self.position)
        self._maybe_snapshot()
        return self.position

    def bulk(self, records: list[dict]) -> int:
        """Append many records in one WAL write. Returns the final position."""
        with self.wal_path.open("a", encoding="utf-8") as f:
            for record in records:
                self._validate(record)
                record = {**record, "_pos": self.position + 1}
                f.write(json.dumps(record) + "\n")
                self.position += 1
                self._wal_records += 1
                self._apply_to_memory(record, self.position)
        self._maybe_snapshot()
        return self.position

    def touch(self, node_id: str, blob: int = 0) -> None:
        """Record that a read walked through this node.

        Telemetry, not truth. Writing a WAL record per node per follow
        made every read a write: it dominated the runtime of the large
        benchmark graphs, it turned a read-only workload into one that
        grows the log forever, and it means a reader needs write access
        to answer a question. The counters live in memory and reach disk
        with the next snapshot, so a crash loses some counts of who
        looked at what, which is the right thing to lose.
        """
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.traffic += 1
        node.blob_traversals += blob

    def wal_len(self) -> int:
        if not self.wal_path.exists():
            return 0
        return sum(1 for _ in self.wal_path.open())

    def _maybe_snapshot(self) -> None:
        """Compact once the WAL has grown past the threshold.

        A snapshot costs the size of the live data, so a fixed threshold
        would make loading a large graph quadratic: a million-node
        ingest would write a million-record run file twenty times. The
        threshold is therefore also at least the live data, which means
        a snapshot never costs more than the WAL that triggered it, and
        the work is amortized to a constant per record.
        """
        if not self.snapshot_every:
            return
        live = len(self.nodes) + len(self.edge_index)
        if self._wal_records >= max(self.snapshot_every, live):
            self.snapshot()

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
                    "props": e.props,
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
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "position": self.position,
                    "id_counters": self.id_counters,
                    "records": records,
                },
                f,
            )
            f.flush()
            # The rename is only atomic with respect to a crash if the
            # bytes are on disk before it happens. Snapshots are rare, so
            # this costs nothing measurable and buys the guarantee.
            os.fsync(f.fileno())
        tmp_path.rename(run_path)
        self.wal_path.write_text("")
        self._wal_records = 0
        self._prune_runs()
        return run_path

    def _prune_runs(self) -> None:
        """Keep the newest runs and delete the rest.

        Replay reads only the newest. The one before it is the fallback
        the corrupt-run message tells an operator to fall back to. Every
        run older than that is a disk leak that grows with history.
        """
        runs = sorted(
            self.path.glob("runs/run-*.json"), key=lambda p: int(p.stem.split("-")[1])
        )
        for stale in runs[: -self.keep_runs] if self.keep_runs else runs:
            stale.unlink(missing_ok=True)

    def _name_key(self, node) -> tuple[str, str] | None:
        from .text import fold

        name = node.props.get("name")
        if not isinstance(name, str):
            return None
        return (node.cls, fold(name))

    def _index_name(self, node) -> None:
        key = self._name_key(node)
        if key is not None:
            self.by_name.setdefault(key, []).append(node.id)

    def _deindex_name(self, node) -> None:
        key = self._name_key(node)
        if key is not None and key in self.by_name:
            ids = [i for i in self.by_name[key] if i != node.id]
            if ids:
                self.by_name[key] = ids
            else:
                del self.by_name[key]

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
            self.by_class.setdefault(node.cls, []).append(node.id)
            self._index_name(node)
            self.edges.setdefault(node.id, [])
            self._bump_counter(node.cls, node.id)
        elif op == "patch_node":
            node = self.nodes[rec["id"]]
            if "name" in rec["props"]:
                self._deindex_name(node)
            for k, v in rec["props"].items():
                if k in node.props and node.props[k] != v:
                    node.conflict_count += 1
                node.props[k] = v
            node.last_confirmed = pos
            if "state" in rec:
                node.state = rec["state"]
            if "name" in rec["props"]:
                self._index_name(node)
        elif op == "put_edge":
            edge = Edge(
                id=rec["id"],
                type=rec["type"],
                roles=dict(rec["roles"]),
                props=dict(rec.get("props") or {}),
                created_at=pos,
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

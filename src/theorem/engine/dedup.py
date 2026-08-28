"""Dedup pipeline: blocking keys (sync, on every assert) plus a
string-similarity sweep standing in for the embedding stage (async shape,
run via sweep()). System detects, agent resolves.
"""

from __future__ import annotations

import difflib

from .storage import Node, Store
from .text import norm_name

SIM_THRESHOLD = 0.85
BLOCK_PREFIX_LEN = 4


def _norm(name: object) -> str:
    return norm_name(name)


def block_key(cls: str, name: object) -> str:
    return f"{cls}:{_norm(name)[:BLOCK_PREFIX_LEN]}"


def _similarity(a: object, b: object) -> float:
    na, nb = _norm(a), _norm(b)
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    # name containment ("Ionix" vs "Ionix Co") is strong duplicate evidence
    if na and nb and na != nb and (na.startswith(nb) or nb.startswith(na)):
        ratio = max(ratio, 0.9)
    return ratio


def _evidence(store: Store, a: Node, b: Node) -> str:
    shared = [
        k
        for k in a.props
        if not k.startswith("_") and k != "name" and a.props.get(k) == b.props.get(k)
    ]
    bits = [f"name {_similarity(a.props.get('name'), b.props.get('name')):.2f}"]
    if shared:
        bits.append("shared: " + ", ".join(f"{k} {a.props[k]}" for k in shared[:3]))
    return "; ".join(bits)


def _candidate(
    store: Store, a: Node, b: Node, threshold: float = SIM_THRESHOLD
) -> dict | None:
    if a.id == b.id or a.cls != b.cls:
        return None
    if frozenset((a.id, b.id)) in store.distinct_pairs:
        return None
    score = _similarity(a.props.get("name", a.id), b.props.get("name", b.id))
    if score < threshold:
        return None
    return {
        "a": a.id,
        "b": b.id,
        "cls": a.cls,
        "score": round(score, 2),
        "evidence": _evidence(store, a, b),
    }


def sync_candidates(
    store: Store, node: Node, threshold: float = SIM_THRESHOLD
) -> list[dict]:
    """Blocking stage: same class + same normalized-name prefix."""
    key = block_key(node.cls, node.props.get("name", ""))
    out = []
    for other in store.nodes.values():
        if other.retired_at is not None or store.resolve(other.id) != other.id:
            continue
        if (
            other.id == node.id
            or block_key(other.cls, other.props.get("name", "")) != key
        ):
            continue
        cand = _candidate(store, other, node, threshold=threshold)
        if cand:
            out.append(cand)
    return out


def record(store: Store, candidates: list[dict]) -> None:
    known = {frozenset((r["a"], r["b"])) for r in store.dup_ledger}
    for cand in candidates:
        if frozenset((cand["a"], cand["b"])) not in known:
            store.apply({"op": "dup", **cand})


def sweep(store: Store) -> int:
    """Similarity stage, async shape: cross-block near-name scan per class."""
    by_cls: dict[str, list[Node]] = {}
    for node in store.nodes.values():
        if node.retired_at is None and store.resolve(node.id) == node.id:
            by_cls.setdefault(node.cls, []).append(node)
    found = 0
    for nodes in by_cls.values():
        for i, a in enumerate(nodes):
            for b in nodes[i + 1 :]:
                cand = _candidate(store, a, b)
                if cand:
                    before = len(store.dup_ledger)
                    record(store, [cand])
                    found += len(store.dup_ledger) - before
    return found

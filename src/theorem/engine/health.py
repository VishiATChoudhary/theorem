"""Per-node health subscores, all in [0, 1]. Spec section: Health."""

from __future__ import annotations

from .storage import Store


def scores(store: Store, node_id: str) -> dict[str, float]:
    node = store.nodes[node_id]
    degree = len([e for e in store.edges.get(node_id, []) if e.retired_at is None])
    loss = min(1.0, node.conflict_count / 5)
    query = min(1.0, len(node.flags) / 3)
    structure = max(
        min(1.0, degree / 100),
        min(1.0, node.blob_traversals / 50),
        0.3 if degree == 0 else 0.0,
    )
    staleness = min(1.0, (store.position - node.last_confirmed) / 1000)
    return {"loss": loss, "query": query, "structure": structure,
            "staleness": staleness}

"""Deterministic staging: turn a normalized Envelope into structure nodes.

Structure nodes (document, chunk, table_blob, media) are written straight
through Store.apply with ids from store.next_id, bypassing assert statements
entirely. Table blobs mirror the exact payload/_rows/state shape that
writes._assert_node produces for `attach:` props, so `refine` works on them
unchanged.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field

from .chunk import split
from .envelope import Envelope

MIME_BY_FORMAT = {
    "markdown": "text/markdown",
    "text": "text/plain",
    "csv": "text/csv",
    "json": "application/json",
    "jsonl": "application/jsonl",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


@dataclass
class StageReceipt:
    doc_id: str
    chunks: int
    tables: int
    media: int
    existing: bool
    lines: list[str] = field(default_factory=list)
    doc_table_ids: list[str] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join(self.lines)


def _origin_page(origin: str) -> int:
    if origin.startswith("page "):
        tail = origin[len("page ") :].strip()
        if tail.isdigit():
            return int(tail)
    return 0


def _part_of_edge(store, doc_id: str, piece_id: str) -> None:
    store.apply(
        {
            "op": "put_edge",
            "id": store.next_id("edge"),
            "type": "part_of",
            "roles": {"piece": piece_id, "whole": doc_id},
        }
    )


def stage(session, envelope: Envelope, filename: str, raw: bytes) -> StageReceipt:
    store = session.store
    digest = hashlib.sha256(raw).hexdigest()

    for node in store.nodes.values():
        if node.cls == "document" and node.props.get("sha256") == digest:
            return StageReceipt(
                doc_id=node.id,
                chunks=0,
                tables=0,
                media=0,
                existing=True,
                lines=[f"receipt: {filename} already staged as {node.id}"],
            )

    chunks = split(envelope.body, envelope.anchors)
    max_page = max((page for _, page in chunks), default=0)
    mime = MIME_BY_FORMAT.get(
        envelope.meta.get("format", ""), "application/octet-stream"
    )

    doc_id = store.next_id("document")
    store.apply(
        {
            "op": "put_node",
            "id": doc_id,
            "cls": "document",
            "props": {
                "title": filename,
                "mime": mime,
                "pages": max_page + 1 if chunks else 0,
                "sha256": digest,
            },
            "state": "atom",
        }
    )

    for ord_, (text, page) in enumerate(chunks):
        cid = store.next_id("chunk")
        store.apply(
            {
                "op": "put_node",
                "id": cid,
                "cls": "chunk",
                "props": {
                    "text": text,
                    "page": page,
                    "ord": ord_,
                    "_source": f"doc:{filename}#p{page}",
                },
                "state": "atom",
            }
        )
        _part_of_edge(store, doc_id, cid)

    doc_table_ids: list[str] = []
    sha8 = digest[:8]
    attach_dir = store.path / "attachments"
    attach_dir.mkdir(parents=True, exist_ok=True)
    for table in envelope.tables:
        page = _origin_page(table.origin)
        key = f"{sha8}-{table.name}"
        fieldnames = list(table.rows[0].keys()) if table.rows else []
        with (attach_dir / f"{key}.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(table.rows)
        tid = store.next_id("table_blob")
        store.apply(
            {
                "op": "put_node",
                "id": tid,
                "cls": "table_blob",
                "props": {
                    "title": table.name,
                    "payload": f"attach:{key}",
                    "_rows": table.rows,
                    "_source": f"doc:{filename}#p{page}",
                },
                "state": "blob",
            }
        )
        _part_of_edge(store, doc_id, tid)
        doc_table_ids.append(tid)

    media_count = 0
    for media in envelope.images:
        page = _origin_page(media.origin)
        mid = store.next_id("media")
        store.apply(
            {
                "op": "put_node",
                "id": mid,
                "cls": "media",
                "props": {
                    "caption": "",
                    "format": media.format,
                    "page": page,
                    "_source": f"doc:{filename}#p{page}",
                },
                "state": "atom",
            }
        )
        _part_of_edge(store, doc_id, mid)
        media_count += 1

    lines = [
        f"receipt: staged {filename} = {doc_id}",
        f"  chunks: {len(chunks)}, tables: {len(doc_table_ids)}, media: {media_count}",
    ]
    return StageReceipt(
        doc_id=doc_id,
        chunks=len(chunks),
        tables=len(doc_table_ids),
        media=media_count,
        existing=False,
        lines=lines,
        doc_table_ids=doc_table_ids,
    )

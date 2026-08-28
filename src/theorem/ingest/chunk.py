"""Deterministic chunker: markdown headings first, pack paragraphs, hard cap."""

from __future__ import annotations

import bisect
import re

from ..engine.executor import count_tokens
from .envelope import Anchor

HEADING_RE = re.compile(r"^#{1,6} ", re.MULTILINE)
TOKEN_CAP = 600
HARD_CUT_CHARS = 2400  # TOKEN_CAP * 4 chars/token, matches count_tokens


def split(body: str, anchors: list[Anchor]) -> list[tuple[str, int]]:
    """Split body into (text, page) chunks, no overlap.

    Segments on markdown headings first, then packs paragraphs (split on
    blank lines) up to a 600-token cap; a paragraph over the cap alone is
    hard-cut at 2400-char boundaries. Page is looked up via anchors at the
    chunk's start offset, 0 when there are no anchors.
    """
    chunks: list[tuple[str, int]] = []
    for seg_text, seg_offset in _segment_by_heading(body):
        for text, offset in _pack_segment(seg_text, seg_offset):
            chunks.append((text, _page_for_offset(offset, anchors)))
    return chunks


def _segment_by_heading(body: str) -> list[tuple[str, int]]:
    starts = [m.start() for m in HEADING_RE.finditer(body)]
    if not starts:
        return [(body, 0)] if body.strip() else []
    segments: list[tuple[str, int]] = []
    if starts[0] > 0 and body[: starts[0]].strip():
        segments.append((body[: starts[0]], 0))
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        segments.append((body[start:end], start))
    return segments


def _pack_segment(seg_text: str, seg_offset: int) -> list[tuple[str, int]]:
    paras = seg_text.split("\n\n")
    offsets = []
    pos = 0
    for para in paras:
        offsets.append(pos)
        pos += len(para) + 2  # + len("\n\n")

    chunks: list[tuple[str, int]] = []
    buffer = ""
    buffer_offset = 0
    for para, local_off in zip(paras, offsets, strict=True):
        if not para.strip():
            continue
        if count_tokens(para) > TOKEN_CAP:
            if buffer.strip():
                chunks.append((buffer, buffer_offset))
                buffer = ""
            for cut in range(0, len(para), HARD_CUT_CHARS):
                piece = para[cut : cut + HARD_CUT_CHARS]
                if piece.strip():
                    chunks.append((piece, seg_offset + local_off + cut))
            continue
        candidate = f"{buffer}\n\n{para}" if buffer else para
        if buffer and count_tokens(candidate) > TOKEN_CAP:
            chunks.append((buffer, buffer_offset))
            buffer = para
            buffer_offset = seg_offset + local_off
        else:
            if not buffer:
                buffer_offset = seg_offset + local_off
            buffer = candidate
    if buffer.strip():
        chunks.append((buffer, buffer_offset))
    return chunks


def _page_for_offset(offset: int, anchors: list[Anchor]) -> int:
    if not anchors:
        return 0
    offsets = [a.offset for a in anchors]
    idx = bisect.bisect_right(offsets, offset) - 1
    if idx < 0:
        return anchors[0].page
    return anchors[idx].page

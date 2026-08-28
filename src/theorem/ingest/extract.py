"""Stage-3 extraction: turn a staged document's chunks into theorem programs
via an agent runner.

Each chunk is prompted independently (task instruction + schema + focus +
provenance rule), the runner's output is treated as a theorem program and
run against the session. A verify failure ("nothing was executed") gets one
repair attempt with the original prompt, the failed program, and the error
appended; a second failure flags the document and counts the chunk as
failed. Token spend is tracked against a budget, checked before each chunk
so the runner is never invoked once the budget would be exceeded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine.executor import count_tokens
from .runners import Runner

VERIFY_FAILURE = "nothing was executed"


@dataclass
class ExtractReceipt:
    chunks_done: int = 0
    chunks_failed: int = 0
    budget_spent: int = 0
    stopped_early: bool = False
    lines: list[str] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join(self.lines)


def _doc_chunks(session, doc_id: str) -> list:
    store = session.store
    chunks = [
        node
        for node in store.nodes.values()
        if node.cls == "chunk"
        and any(
            edge.type == "part_of"
            and edge.roles.get("piece") == node.id
            and edge.roles.get("whole") == doc_id
            for edge in store.edges.get(node.id, [])
        )
    ]
    chunks.sort(key=lambda n: n.props["ord"])
    return chunks


def _header(session, focus: str) -> str:
    parts = [
        "Read the chunk of text below and emit a theorem program that "
        "asserts the facts it contains.",
        session.schema.render(),
    ]
    if focus:
        parts.append(f"Focus: {focus}")
    parts.append(
        "Every statement must end with a provenance clause: source doc:<title>#p<page>."
    )
    return "\n\n".join(parts)


def extract(
    session,
    doc_id: str,
    runner: Runner,
    budget: int = 50_000,
    focus: str = "",
) -> ExtractReceipt:
    receipt = ExtractReceipt()
    header = _header(session, focus)

    for chunk in _doc_chunks(session, doc_id):
        prompt = f"{header}\n\n{chunk.props['text']}"
        prompt_cost = count_tokens(prompt)
        if receipt.budget_spent + prompt_cost >= budget:
            receipt.stopped_early = True
            break

        output = runner.run(prompt)
        receipt.budget_spent += prompt_cost + count_tokens(output)
        result = session.run(output)

        if VERIFY_FAILURE in result:
            repair_prompt = f"{prompt}\n\n{output}\n\n{result}"
            output = runner.run(repair_prompt)
            receipt.budget_spent += count_tokens(repair_prompt) + count_tokens(output)
            result = session.run(output)

            if VERIFY_FAILURE in result:
                ord_ = chunk.props["ord"]
                reason = f"extract failed chunk {ord_}"
                session.run(f'flag {doc_id} reason "{reason}"')
                receipt.chunks_failed += 1
                receipt.lines.append(f"chunk {ord_}: flagged, {reason}")
                continue

        receipt.chunks_done += 1
        receipt.lines.append(f"chunk {chunk.props['ord']}: done")

    return receipt

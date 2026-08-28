"""Playbook compilation: a natural-language markdown use case compiled to a
verified theorem program of schema declarations.

The playbook file stages as a document node (sha256-deduped, like any other
ingested file). An agent runner is prompted with the playbook text plus the
live schema and the `derive` grammar, and answers with three fenced blocks:
```theorem``` (a program of `derive class`/`derive edge` statements),
```summary``` (plain-language justification, one quote per class), and
```focus``` (extraction guidance stored on the document node). The program
is parsed and verified dry (no live mutation) before anything is shown to
the user; a VerifyError/ParseError gets one repair retry with the error fed
back to the agent. Guided mode asks for confirmation before applying;
unhinged mode applies immediately.

Recompiling an edited playbook diffs the newly applied program against
classes previously derived from *any* playbook: a class that lineage says
came from a playbook, is not yet deprecated, and whose name is absent from
the freshly applied program gets deprecated (never deleted).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..ast_nodes import DeriveClass, DeriveEdge
from ..engine.writes import deprecate_class
from ..parser import ParseError, parse
from ..verifier import VerifyError, verify
from .normalize import normalize
from .runners import Runner
from .stage import stage

BLOCK_RE = re.compile(r"```(theorem|summary|focus)\n(.*?)\n```", re.DOTALL)

DERIVE_GRAMMAR = (
    "derive class NAME from BASE with {prop: type, ...} [quota N] [dedup X]\n"
    "derive edge NAME(role1: CLASS, role2: CLASS)\n"
    "Classes derive from entity or from each other; edges name exactly two roles."
)

WORKED_EXAMPLE = """Worked example.

Playbook excerpt:
    ## What we track
    Companies that compete with us, their products, and pricing.

Response:
```theorem
derive class competitor from entity with {hq_country: str} quota 50
derive edge competes_with(us: competitor, them: competitor)
```
```summary
competitor: "Companies that compete with us" (quote). competes_with: rivalry link.
```
```focus
Prioritize launch dates. Ignore boilerplate.
```"""

RULES = (
    "Read the playbook below and propose theorem schema declarations for it.\n"
    "Answer with exactly three fenced blocks, tagged theorem, summary, and "
    "focus, in that order. The theorem block holds only derive class / "
    "derive edge statements. The summary block must justify every class you "
    "propose with a direct quote from the playbook. The focus block states, "
    "in plain language, what matters most and what to ignore during "
    "extraction."
)


@dataclass
class PlaybookReceipt:
    doc_id: str
    applied: list[str] = field(default_factory=list)
    deprecated: list[str] = field(default_factory=list)
    focus: str = ""
    aborted: bool = False
    lines: list[str] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join(self.lines)


def _prompt(schema_render: str, playbook_text: str) -> str:
    return "\n\n".join(
        [
            RULES,
            f"Grammar:\n{DERIVE_GRAMMAR}",
            WORKED_EXAMPLE,
            f"Current schema:\n{schema_render}",
            f"Playbook:\n{playbook_text}",
        ]
    )


def _parse_blocks(output: str) -> dict[str, str]:
    return {tag: body.strip() for tag, body in BLOCK_RE.findall(output)}


def _dry_check(program: str, schema) -> list:
    stmts = parse(program)
    verify(stmts, schema)
    return stmts


def compile_playbook(
    session,
    path: Path,
    runner: Runner,
    unhinged: bool = False,
    confirm: Callable[[str], bool] | None = None,
) -> PlaybookReceipt:
    if not unhinged and confirm is None:
        raise ValueError("confirm is required unless unhinged=True")

    store = session.store
    raw = path.read_bytes()
    envelope = normalize(raw, path.name)
    stage_receipt = stage(session, envelope, path.name, raw)
    doc_id = stage_receipt.doc_id

    prompt = _prompt(session.schema.render(), envelope.body)
    output = runner.run(prompt)
    blocks = _parse_blocks(output)
    program = blocks.get("theorem", "")
    summary = blocks.get("summary", "")
    focus = blocks.get("focus", "")

    try:
        stmts = _dry_check(program, session.schema)
    except (ParseError, VerifyError) as e:
        repair_prompt = f"{prompt}\n\n{output}\n\nerror: {e}"
        output = runner.run(repair_prompt)
        blocks = _parse_blocks(output)
        program = blocks.get("theorem", "")
        summary = blocks.get("summary", "")
        focus = blocks.get("focus", "")
        stmts = _dry_check(program, session.schema)  # let a second failure raise

    receipt = PlaybookReceipt(doc_id=doc_id, focus=focus)

    if not unhinged and not confirm(program + "\n\n" + summary):
        receipt.aborted = True
        receipt.lines.append(
            f"receipt: playbook {doc_id} compile aborted (not confirmed)"
        )
        return receipt

    session.run(program)

    new_names = {
        stmt.name for stmt in stmts if isinstance(stmt, (DeriveClass, DeriveEdge))
    }

    linked_names: list[str] = []
    for rec in store.lineage:
        if rec.get("kind") in ("derive_class", "derive_edge") and "playbook" not in rec:
            name = rec["child"] if rec["kind"] == "derive_class" else rec["name"]
            rec["playbook"] = doc_id
            linked_names.append(name)
    if linked_names:
        store.apply(
            {
                "op": "lineage",
                "kind": "playbook_link",
                "playbook": doc_id,
                "names": linked_names,
            }
        )
    receipt.applied = linked_names

    store.apply({"op": "patch_node", "id": doc_id, "props": {"_focus": focus}})

    for rec in store.lineage:
        if rec.get("kind") != "derive_class" or "playbook" not in rec:
            continue
        name = rec["child"]
        if name in new_names:
            continue
        cdef = session.schema.classes.get(name)
        if cdef is None or cdef.status == "deprecated":
            continue
        deprecate_class(session, name)
        receipt.deprecated.append(name)

    receipt.lines.append(f"receipt: playbook {doc_id} compiled")
    receipt.lines.append(f"  applied: {', '.join(receipt.applied) or '(none)'}")
    if receipt.deprecated:
        receipt.lines.append(f"  deprecated: {', '.join(receipt.deprecated)}")
    return receipt

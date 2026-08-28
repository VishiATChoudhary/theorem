"""Write surface: every verb returns a structured receipt.

The receipt is the system's half of the conversation: what changed, which
guards ran, and any duplicate candidates the write triggered.
"""

from __future__ import annotations

import csv
import difflib
from dataclasses import dataclass, field

from ..ast_nodes import (
    AssertEdge,
    AssertNode,
    Compact,
    DeriveClass,
    DeriveEdge,
    Distinct,
    Flag,
    Merge,
    Refine,
    Retire,
    Stmt,
)
from ..schema import ClassDef, EdgeDef, Schema
from . import dedup
from .storage import Store

PROVISIONAL_QUOTA = 500


class WriteError(Exception):
    pass


@dataclass
class WriteContext:
    store: Store
    schema: Schema
    env: dict[str, object] = field(
        default_factory=dict
    )  # name -> node id | list[node id]

    def resolve_ref(self, ref: str) -> str:
        if ref.startswith("#"):
            nid = self.store.resolve(ref)
            if nid not in self.store.nodes:
                raise WriteError(f"unknown node id {ref}")
            return nid
        value = self.env.get(ref)
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        if isinstance(value, str):
            return self.store.resolve(value)
        if isinstance(value, list):
            raise WriteError(
                f'"{ref}" is bound to {len(value)} nodes; need exactly one'
            )
        raise WriteError(f'"{ref}" is not bound to a node')


@dataclass
class Receipt:
    lines: list[str]
    dup_candidates: list[dict] = field(default_factory=list)

    def render(self) -> str:
        out = list(self.lines)
        if self.dup_candidates:
            out.append(f"  dup candidates: {len(self.dup_candidates)}")
            for c in self.dup_candidates:
                out.append(f'    {c["a"]} {c["cls"]} "{c["name"]}" score {c["score"]}')
                if c.get("evidence"):
                    out.append(f"      {c['evidence']}")
            out.append("  resolve with: merge / distinct")
        return "\n".join(out)


def _quota_check(ctx: WriteContext, cls: str) -> None:
    cdef = ctx.schema.classes[cls]
    if cdef.status == "provisional" and cdef.quota is not None:
        count = sum(1 for n in ctx.store.nodes.values() if n.cls == cls)
        if count >= cdef.quota:
            raise WriteError(
                f"class {cls} is provisional and at quota ({cdef.quota} instances)"
            )


def _load_attachment(ctx: WriteContext, ref: str) -> list[dict]:
    key = ref.split(":", 1)[1]
    attach_dir = (ctx.store.path / "attachments").resolve()
    path = (attach_dir / f"{key}.csv").resolve()
    if not path.is_relative_to(attach_dir):
        raise WriteError(f"attachment key {key!r} escapes the attachments directory")
    if not path.exists():
        raise WriteError(f"attachment {ref} not found at {path}")
    # utf-8-sig: a BOM would otherwise become part of the first header name
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _assert_node(stmt: AssertNode, ctx: WriteContext) -> Receipt:
    store = ctx.store
    _quota_check(ctx, stmt.cls)
    props = dict(stmt.props)
    state = "atom"
    rows = None
    for value in props.values():
        if isinstance(value, str) and value.startswith("attach:"):
            rows = _load_attachment(ctx, value)
            state = "blob"
    if stmt.cls == "table_blob":
        state = "blob"
    nid = store.next_id(stmt.cls)
    record = {
        "op": "put_node",
        "id": nid,
        "cls": stmt.cls,
        "props": props,
        "state": state,
    }
    if stmt.source:
        props["_source"] = stmt.source
    if rows is not None:
        props["_rows"] = rows
    pos = store.apply(record)
    ctx.env[stmt.name] = nid
    cands = dedup.sync_candidates(store, store.nodes[nid])
    dedup.record(store, cands)
    display = [
        {**c, "name": store.nodes[c["a"]].props.get("name", c["a"])} for c in cands
    ]
    return Receipt(
        [
            f"receipt: created {stmt.cls} {stmt.name} = {nid} at @t-{pos}",
            "  guards: schema ok, class invariants ok",
        ],
        display,
    )


def _assert_edge(stmt: AssertEdge, ctx: WriteContext) -> Receipt:
    store = ctx.store
    roles = {role: ctx.resolve_ref(ref) for role, ref in stmt.role_refs.items()}
    edef = ctx.schema.edges[stmt.edge]
    for role, nid in roles.items():
        want = edef.roles[role]
        got = store.nodes[nid].cls
        base_chain = {got}
        c = ctx.schema.classes.get(got)
        while c is not None and c.base:
            base_chain.add(c.base)
            c = ctx.schema.classes.get(c.base)
        if want not in base_chain:
            raise WriteError(
                f"role {role} of {stmt.edge} takes a {want}; {nid} is a {got}"
            )
    eid = store.next_id("edge")
    pos = store.apply({"op": "put_edge", "id": eid, "type": stmt.edge, "roles": roles})
    role_str = ", ".join(f"{r}: {n}" for r, n in roles.items())
    return Receipt(
        [
            f"receipt: created edge {stmt.edge}({role_str}) = {eid} at @t-{pos}",
            "  guards: schema ok, roles ok",
        ]
    )


def _merge(stmt: Merge, ctx: WriteContext) -> Receipt:
    store = ctx.store
    a = ctx.resolve_ref(stmt.a)
    b = ctx.resolve_ref(stmt.b)
    if a == b:
        # the user usually means "merge with my duplicate": consult the ledger
        pending = []
        for rec in ctx.store.dup_ledger:
            ra, rb = ctx.store.resolve(rec["a"]), ctx.store.resolve(rec["b"])
            pair = frozenset((ra, rb))
            if a in pair and len(pair) == 2 and pair not in ctx.store.distinct_pairs:
                pending.append((rec["score"], rb if ra == a else ra))
        hint = ""
        if pending:
            _, other = max(pending)
            name = ctx.store.nodes[other].props.get("name", other)
            hint = (
                f'; {a} has a pending dup candidate {other} ("{name}"). '
                f"did you mean: merge {a}, {other}"
            )
        raise WriteError(f"merge of a node with itself{hint}")
    na, nb = store.nodes[a], store.nodes[b]
    if na.cls != nb.cls:
        raise WriteError(f"cannot merge {na.cls} with {nb.cls}")
    survivor, absorbed = (na, nb) if na.created_at <= nb.created_at else (nb, na)
    pre_states = {
        n.id: {
            "props": {k: v for k, v in n.props.items() if not k.startswith("_")},
            "state": n.state,
            "created_at": n.created_at,
        }
        for n in (na, nb)
    }
    # property reconciliation
    merged: dict[str, object] = {}
    if stmt.policy == "newest":
        newer, older = (na, nb) if na.created_at > nb.created_at else (nb, na)
        for k, v in older.props.items():
            merged[k] = v
        for k, v in newer.props.items():
            merged[k] = v
    elif stmt.policy.startswith("source "):
        want_src = stmt.policy.split(" ", 1)[1]
        if na.props.get("_source") == want_src:
            preferred, other = na, nb
        elif nb.props.get("_source") == want_src:
            preferred, other = nb, na
        else:
            raise WriteError(
                f"neither node has source {want_src}; "
                f"use prefer newest or explicit values"
            )
        merged = {**other.props, **preferred.props}
    else:
        raise WriteError(f"unknown merge policy {stmt.policy!r}")
    merged = {k: v for k, v in merged.items() if not k.startswith("_")}
    store.apply(
        {
            "op": "lineage",
            "kind": "merge",
            "survivor": survivor.id,
            "absorbed": absorbed.id,
            "pre_states": pre_states,
            "policy": stmt.policy,
        }
    )
    # re-home absorbed node's edges onto the survivor
    for edge in list(store.edges.get(absorbed.id, [])):
        if edge.retired_at is not None:
            continue
        new_roles = {
            r: (survivor.id if store.resolve(nid) == absorbed.id else nid)
            for r, nid in edge.roles.items()
        }
        store.apply({"op": "retire_edge", "id": edge.id})
        store.apply(
            {
                "op": "put_edge",
                "id": store.next_id("edge"),
                "type": edge.type,
                "roles": new_roles,
            }
        )
    store.apply({"op": "alias", "absorbed": absorbed.id, "survivor": survivor.id})
    pos = store.apply({"op": "patch_node", "id": survivor.id, "props": merged})
    store.apply(
        {"op": "retire", "id": absorbed.id, "reason": f"merged into {survivor.id}"}
    )
    return Receipt(
        [
            f"receipt: merged -> {survivor.id} (lineage keeps both) at @t-{pos}",
            f"  absorbed {absorbed.id} is now an alias of {survivor.id}",
            f"  policy: prefer {stmt.policy}",
        ]
    )


def _distinct(stmt: Distinct, ctx: WriteContext) -> Receipt:
    a = ctx.resolve_ref(stmt.a)
    b = ctx.resolve_ref(stmt.b)
    if a == b:
        raise WriteError(
            f"distinct needs two different nodes; both refs resolve to {a}"
        )
    pos = ctx.store.apply({"op": "distinct", "a": a, "b": b, "reason": stmt.reason})
    ctx.store.dup_ledger[:] = [
        r
        for r in ctx.store.dup_ledger
        if frozenset((ctx.store.resolve(r["a"]), ctx.store.resolve(r["b"])))
        != frozenset((a, b))
    ]
    return Receipt(
        [
            f"receipt: distinct {a}, {b} recorded at @t-{pos}",
            "  pair suppressed from future dup candidates",
        ]
    )


def _coerce(value: str, typ: str):
    if typ == "int":
        return int(value)
    if typ == "float":
        return float(value)
    if typ == "bool":
        return value.strip().lower() in ("true", "1", "yes")
    return value


def _refine(stmt: Refine, ctx: WriteContext) -> Receipt:
    store, schema = ctx.store, ctx.schema
    blob_id = ctx.resolve_ref(stmt.ref)
    blob = store.nodes[blob_id]
    rows = blob.props.get("_rows")
    if not rows:
        raise WriteError(f"{blob_id} has no tabular payload to refine")
    target_props = schema.all_props(stmt.into_cls)
    for target, source_col in stmt.mapping.items():
        if target not in target_props:
            raise WriteError(f"class {stmt.into_cls} has no property {target}")
        if source_col not in rows[0]:
            raise WriteError(
                f"payload has no column {source_col!r}; columns are {list(rows[0])}"
            )
    child_ids = []
    for row in rows:
        props = {t: _coerce(row[s], target_props[t]) for t, s in stmt.mapping.items()}
        cid = store.next_id(stmt.into_cls)
        store.apply(
            {
                "op": "put_node",
                "id": cid,
                "cls": stmt.into_cls,
                "props": props,
                "state": "atom",
                "origin": blob_id,
            }
        )
        store.apply(
            {
                "op": "lineage",
                "kind": "refine",
                "parent": blob_id,
                "child": cid,
                "mapping": stmt.mapping,
            }
        )
        child_ids.append(cid)
    pos = store.apply(
        {"op": "patch_node", "id": blob_id, "props": {}, "state": "composite"}
    )
    n_dups = 0
    for cid in child_ids:
        cands = dedup.sync_candidates(store, store.nodes[cid])
        cands = [c for c in cands if c["a"] not in child_ids]
        dedup.record(store, cands)
        n_dups += len(cands)
    ctx.env[stmt.name] = child_ids
    lines = [
        f"receipt: refined {blob_id} -> {len(child_ids)} {stmt.into_cls} nodes at @t-{pos}",
        f"  lineage: each new node carries origin {blob_id}",
    ]
    if n_dups:
        lines.append(f"  dup candidates: {n_dups} (queued per class)")
    lines.append("  blob state: composite, retained as lineage parent (cold)")
    return Receipt(lines)


def _compact(stmt: Compact, ctx: WriteContext) -> Receipt:
    store = ctx.store
    members = ctx.env.get(stmt.src)
    if isinstance(members, str):
        members = [members]
    if not isinstance(members, list) or not members:
        raise WriteError(f'"{stmt.src}" is not bound to a node set')
    classes = {store.nodes[store.resolve(m)].cls for m in members}
    if len(classes) != 1:
        raise WriteError(f"compact needs one class, got {sorted(classes)}")
    cls = classes.pop()
    sid = store.next_id(cls)
    store.apply(
        {
            "op": "put_node",
            "id": sid,
            "cls": cls,
            "props": dict(stmt.props),
            "state": "composite",
        }
    )
    for m in members:
        mid = store.resolve(m)
        store.apply({"op": "lineage", "kind": "compact", "parent": sid, "child": mid})
        store.apply({"op": "retire", "id": mid, "reason": f"compacted into {sid}"})
    pos = store.position
    ctx.env[stmt.name] = sid
    return Receipt(
        [
            f"receipt: compacted {len(members)} {cls} nodes -> {sid} at @t-{pos}",
            "  members retired, reachable through lineage",
        ]
    )


def _retire(stmt: Retire, ctx: WriteContext) -> Receipt:
    nid = ctx.resolve_ref(stmt.ref)
    pos = ctx.store.apply({"op": "retire", "id": nid, "reason": stmt.reason})
    return Receipt(
        [
            f"receipt: retired {nid} at @t-{pos}",
            f"  reason: {stmt.reason}",
            "  node remains queryable through lineage; excluded from current reads",
        ]
    )


def _flag(stmt: Flag, ctx: WriteContext) -> Receipt:
    nid = ctx.resolve_ref(stmt.ref)
    pos = ctx.store.apply({"op": "flag", "id": nid, "reason": stmt.reason})
    return Receipt([f"receipt: flagged {nid} at @t-{pos}", "  health.query updated"])


def _derive(stmt: DeriveClass, ctx: WriteContext) -> Receipt:
    schema = ctx.schema
    # durable record FIRST: if the append fails, the live schema must not
    # hold a class that would silently vanish on restart
    pos = ctx.store.apply(
        {
            "op": "lineage",
            "kind": "derive_class",
            "child": stmt.name,
            "parent": stmt.base,
            "props": stmt.props,
            "quota": PROVISIONAL_QUOTA,
        }
    )
    schema.classes[stmt.name] = ClassDef(
        name=stmt.name,
        props=dict(stmt.props),
        base=stmt.base,
        status="provisional",
        quota=PROVISIONAL_QUOTA,
    )
    lines = [
        f"receipt: class {stmt.name} provisional at @t-{pos}",
        f"  quota: {PROVISIONAL_QUOTA} instances; promotion needs stable use + dedup review",
    ]
    similar = difflib.get_close_matches(
        stmt.name, [c for c in schema.classes if c != stmt.name], n=1, cutoff=0.7
    )
    if similar:
        score = difflib.SequenceMatcher(None, stmt.name, similar[0]).ratio()
        lines.append(
            f'  note: similar existing class "{similar[0]}" '
            f"(score {score:.2f}), review advised"
        )
    return Receipt(lines)


def _derive_edge(stmt: DeriveEdge, ctx: WriteContext) -> Receipt:
    schema = ctx.schema
    # durable record FIRST: if the append fails, the live schema must not
    # hold an edge that would silently vanish on restart
    pos = ctx.store.apply(
        {
            "op": "lineage",
            "kind": "derive_edge",
            "name": stmt.name,
            "roles": stmt.roles,
        }
    )
    schema.edges[stmt.name] = EdgeDef(stmt.name, dict(stmt.roles))
    return Receipt([f"receipt: edge {stmt.name} declared at @t-{pos}"])


def execute_write(stmt: Stmt, ctx: WriteContext) -> Receipt:
    match stmt:
        case AssertNode():
            return _assert_node(stmt, ctx)
        case AssertEdge():
            return _assert_edge(stmt, ctx)
        case Merge():
            return _merge(stmt, ctx)
        case Distinct():
            return _distinct(stmt, ctx)
        case Refine():
            return _refine(stmt, ctx)
        case Compact():
            return _compact(stmt, ctx)
        case Retire():
            return _retire(stmt, ctx)
        case Flag():
            return _flag(stmt, ctx)
        case DeriveClass():
            return _derive(stmt, ctx)
        case DeriveEdge():
            return _derive_edge(stmt, ctx)
        case _:
            raise WriteError(f"not a write statement: {type(stmt).__name__}")

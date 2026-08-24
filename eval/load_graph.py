"""Load a CypherBench simplekg graph + schema into a GraphLang Session.

Deterministic schema derivation rules (documented for reproducibility):
- Node class name = entity label, lowercased (Team -> team).
- Every class gets a "name" str property plus its declared properties.
- Edge type name = relation label unchanged (playsFor).
- Role names: subj role = subj_label lowercased, obj role = obj_label
  lowercased; when both ends share a label, roles are "subj" and "obj".
- Relation properties (edge properties) are NOT loaded; questions needing
  them are excluded from the eval slice (reported in results).
- list[...] properties load as comma-joined strings so `contains` works.
- date properties load as ISO strings (string comparison preserves order).
"""

from __future__ import annotations

import json
from pathlib import Path

from graphlang.engine.storage import Store
from graphlang.schema import ClassDef, EdgeDef, Schema

TYPE_MAP = {"int": "int", "float": "float", "str": "str", "bool": "bool",
            "date": "str"}


def class_name(label: str) -> str:
    return label.lower()


def role_names(subj_label: str, obj_label: str) -> tuple[str, str]:
    if subj_label == obj_label:
        return "subj", "obj"
    return class_name(subj_label), class_name(obj_label)


def derive_schema(cb_schema: dict) -> Schema:
    schema = Schema()
    for ent in cb_schema["entities"]:
        props = {"name": "str"}
        for pname, ptype in ent.get("properties", {}).items():
            props[pname] = TYPE_MAP.get(ptype.replace("list[", "").replace("]", ""), "str") \
                if not ptype.startswith("list[") else "str"
        schema.classes[class_name(ent["label"])] = ClassDef(
            name=class_name(ent["label"]), props=props)
    for rel in cb_schema["relations"]:
        subj_role, obj_role = role_names(rel["subj_label"], rel["obj_label"])
        schema.edges[rel["label"]] = EdgeDef(
            name=rel["label"],
            roles={subj_role: class_name(rel["subj_label"]),
                   obj_role: class_name(rel["obj_label"])})
    return schema


def _prop_value(v):
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return v


def load(graph_path: str | Path, store: Store) -> dict[str, str]:
    """Bulk-load a simplekg JSON into the store. Returns eid -> node id map."""
    kg = json.loads(Path(graph_path).read_text())
    id_map: dict[str, str] = {}
    records: list[dict] = []
    for ent in kg["entities"]:
        cls = class_name(ent["label"])
        props = {"name": ent.get("name") or ent["eid"]}
        for pname, pval in (ent.get("properties") or {}).items():
            if pval is not None:
                props[pname] = _prop_value(pval)
        nid = store.next_id(cls)
        records.append({"op": "put_node", "id": nid, "cls": cls, "props": props})
        id_map[ent["eid"]] = nid
    schema_roles = {}
    for rel in kg["relations"]:
        label = rel["label"]
        if label not in schema_roles:
            subj_label = rel["subj_id"].split("#")[0]
            obj_label = rel["obj_id"].split("#")[0]
            schema_roles[label] = role_names(subj_label, obj_label)
        subj_role, obj_role = schema_roles[label]
        subj = id_map.get(rel["subj_id"])
        obj = id_map.get(rel["obj_id"])
        if subj is None or obj is None:
            continue
        records.append({"op": "put_edge", "id": store.next_id("edge"),
                        "type": label, "roles": {subj_role: subj, obj_role: obj}})
    store.bulk(records)
    return id_map

"""Load a CypherBench simplekg graph + schema into a theorem Session.

Deterministic schema derivation rules (documented for reproducibility):
- Node class name = entity label, lowercased (Team -> team).
- Every class gets a "name" str property plus its declared properties.
- Edge type name = relation label unchanged (playsFor), except where one
  label connects several pairs of entity labels (geography reuses
  locatedIn for Mountain->Country and Country->Continent). A theorem edge
  type has one fixed pair of roles, so each variant becomes its own type,
  named label_subj_obj (locatedIn_mountain_country). Keying by the bare
  label instead would keep only the last variant, hiding most of the
  graph from the schema and leaving edges with roles their type does not
  declare.
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

from theorem.engine.storage import Store
from theorem.schema import ClassDef, EdgeDef, Schema

TYPE_MAP = {"int": "int", "float": "float", "str": "str", "bool": "bool", "date": "str"}


def class_name(label: str) -> str:
    return label.lower()


def role_names(subj_label: str, obj_label: str) -> tuple[str, str]:
    if subj_label == obj_label:
        return "subj", "obj"
    return class_name(subj_label), class_name(obj_label)


def edge_type_map(cb_schema: dict) -> dict[tuple[str, str, str], str]:
    """(label, subj_label, obj_label) -> theorem edge type name.

    Unambiguous labels keep their name; overloaded ones are split per
    endpoint pair so each theorem edge type has a single role pair.
    """
    variants: dict[str, list[tuple[str, str]]] = {}
    for rel in cb_schema["relations"]:
        variants.setdefault(rel["label"], []).append(
            (rel["subj_label"], rel["obj_label"])
        )
    names = {}
    for label, pairs in variants.items():
        for subj, obj in pairs:
            if len(pairs) == 1:
                names[(label, subj, obj)] = label
            else:
                names[(label, subj, obj)] = (
                    f"{label}_{class_name(subj)}_{class_name(obj)}"
                )
    return names


def derive_schema(cb_schema: dict) -> Schema:
    schema = Schema()
    for ent in cb_schema["entities"]:
        props = {"name": "str"}
        for pname, ptype in ent.get("properties", {}).items():
            props[pname] = (
                TYPE_MAP.get(ptype.replace("list[", "").replace("]", ""), "str")
                if not ptype.startswith("list[")
                else "str"
            )
        schema.classes[class_name(ent["label"])] = ClassDef(
            name=class_name(ent["label"]), props=props
        )
    names = edge_type_map(cb_schema)
    for rel in cb_schema["relations"]:
        subj_role, obj_role = role_names(rel["subj_label"], rel["obj_label"])
        name = names[(rel["label"], rel["subj_label"], rel["obj_label"])]
        schema.edges[name] = EdgeDef(
            name=name,
            roles={
                subj_role: class_name(rel["subj_label"]),
                obj_role: class_name(rel["obj_label"]),
            },
        )
    return schema


def _prop_value(v):
    # Multi-valued properties stay lists. Joining them into one string
    # made "one of these citizenships is Japan" unaskable and made the
    # value itself unreturnable in the shape it was stored in.
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
    # Each edge's type is resolved from its own endpoint labels, so an
    # overloaded relation label lands on the same type derive_schema
    # declared for that pair. Deriving the roles once per label from the
    # first instance seen would give later variants role names their type
    # does not declare, which fails as a KeyError mid-query.
    names = edge_type_map(kg["schema"])
    for rel in kg["relations"]:
        subj_label = rel["subj_id"].split("#")[0]
        obj_label = rel["obj_id"].split("#")[0]
        name = names.get((rel["label"], subj_label, obj_label))
        if name is None:
            continue  # endpoint pair the schema does not declare
        subj_role, obj_role = role_names(subj_label, obj_label)
        subj = id_map.get(rel["subj_id"])
        obj = id_map.get(rel["obj_id"])
        if subj is None or obj is None:
            continue
        records.append(
            {
                "op": "put_edge",
                "id": store.next_id("edge"),
                "type": name,
                "roles": {subj_role: subj, obj_role: obj},
            }
        )
    store.bulk(records)
    return id_map

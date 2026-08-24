"""Schema model: node classes with typed properties, edge types with named roles."""

from __future__ import annotations

from dataclasses import dataclass, field

GRANULARITY_STATES = {"blob", "composite", "atom"}


@dataclass
class ClassDef:
    name: str
    props: dict[str, str]  # prop name -> type name: str|int|float|bool
    base: str | None = None
    allowed_states: set[str] = field(default_factory=lambda: set(GRANULARITY_STATES))
    status: str = "stable"  # stable | provisional
    quota: int | None = None


@dataclass
class EdgeDef:
    name: str
    roles: dict[str, str]  # role name -> class name, exactly two roles

    def other_role(self, role: str) -> str:
        for r in self.roles:
            if r != role:
                return r
        raise KeyError(role)


@dataclass
class Schema:
    classes: dict[str, ClassDef] = field(default_factory=dict)
    edges: dict[str, EdgeDef] = field(default_factory=dict)

    def all_props(self, cls: str) -> dict[str, str]:
        """Props of a class including inherited base-class props."""
        out: dict[str, str] = {}
        chain = []
        cdef = self.classes.get(cls)
        while cdef is not None:
            chain.append(cdef)
            cdef = self.classes.get(cdef.base) if cdef.base else None
        for cdef in reversed(chain):
            out.update(cdef.props)
        return out

    @staticmethod
    def supply_chain() -> "Schema":
        """The running-example schema from the design docs."""
        s = Schema()
        s.classes["product"] = ClassDef("product", {"name": "str", "launch_year": "int"})
        s.classes["part"] = ClassDef("part", {"name": "str", "unit_cost": "float"})
        s.classes["supplier"] = ClassDef("supplier", {"name": "str", "country": "str"})
        s.classes["table_blob"] = ClassDef(
            "table_blob", {"title": "str", "payload": "str"},
            allowed_states={"blob", "composite"})
        s.edges["uses"] = EdgeDef("uses", {"whole": "product", "component": "part"})
        s.edges["supplied_by"] = EdgeDef("supplied_by", {"item": "part", "source": "supplier"})
        return s

    def render(self) -> str:
        """Explainer-format schema listing."""
        lines = ["classes:"]
        for c in self.classes.values():
            props = ", ".join(c.props)
            suffix = ""
            if c.status == "provisional":
                suffix = f"  (provisional, quota {c.quota})"
            base = f" from {c.base}" if c.base else ""
            lines.append(f"  {c.name}{{{props}}}{base}{suffix}")
        lines.append("edges:")
        for e in self.edges.values():
            roles = ", ".join(f"{r}: {cls}" for r, cls in e.roles.items())
            lines.append(f"  {e.name}({roles})")
        return "\n".join(lines)

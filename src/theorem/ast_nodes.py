"""AST node definitions for theorem statements.

Col is a tuple of dotted path segments: ("sups", "name") for sups.name.
Cond is a list of (joiner, Clause) pairs; the first joiner is always "and".
"""

from __future__ import annotations

from dataclasses import dataclass, field

Col = tuple[str, ...]


@dataclass
class Clause:
    col: Col
    op: str  # = != > >= < <= contains
    value: object


Cond = list[tuple[str, Clause]]  # joiner is "and" | "or"


@dataclass
class Stmt:
    line: int = field(default=0, kw_only=True)


@dataclass
class Find(Stmt):
    target: str  # class name, or "nodes" | "dup_candidates" | "class"
    cond: Cond
    name: str
    order_by: Col | None = None
    desc: bool = False


@dataclass
class Follow(Stmt):
    src: str
    edge: str
    role: str
    name: str
    cond: Cond = field(default_factory=list)  # filters the arrival node
    optional: bool = False  # "or none": keep rows that matched nothing


@dataclass
class Or(Stmt):
    """Separates alternative branches; their results are unioned."""


@dataclass
class GroupBy(Stmt):
    col: Col
    name: str


@dataclass
class Aggregate(Stmt):
    op: str  # count sum avg min max
    distinct: bool
    col: Col
    name: str


@dataclass
class Compute(Stmt):
    left: Col
    op: str  # plus minus times over same
    right: Col
    name: str


@dataclass
class Return(Stmt):
    cols: list[Col]
    order_by: Col | None
    desc: bool
    limit: int | None
    budget: int  # defaulted to 2000 when unstated
    after: str | None  # position token @t-N


@dataclass
class Continue(Stmt):
    handle: str  # continuation token @cXXXX
    budget: int


@dataclass
class AssertNode(Stmt):
    cls: str
    props: dict[str, object]
    source: str | None
    name: str


@dataclass
class AssertEdge(Stmt):
    edge: str
    role_refs: dict[str, str]  # role name -> binding name or node id
    source: str | None


@dataclass
class Merge(Stmt):
    a: str
    b: str
    policy: str  # "newest" or "source <provenance>"


@dataclass
class Distinct(Stmt):
    a: str
    b: str
    reason: str


@dataclass
class Refine(Stmt):
    ref: str
    into_cls: str
    mapping: dict[str, str]  # target prop -> source column name
    name: str


@dataclass
class Compact(Stmt):
    src: str
    name: str
    props: dict[str, object]


@dataclass
class Retire(Stmt):
    ref: str
    reason: str


@dataclass
class Flag(Stmt):
    ref: str
    reason: str


@dataclass
class DeriveClass(Stmt):
    name: str
    base: str
    props: dict[str, str]  # prop name -> type name (str|int|float|bool)
    quota: int | None = None
    dedup: float | None = None


@dataclass
class DeriveEdge(Stmt):
    name: str
    roles: dict[str, str]  # role name -> class name, exactly two


@dataclass
class SchemaStmt(Stmt):
    pass

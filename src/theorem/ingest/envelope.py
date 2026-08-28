from dataclasses import dataclass, field


@dataclass
class Table:
    name: str
    rows: list[dict[str, str]]
    origin: str  # "page 3" / "sheet Sales" / "slide 2"


@dataclass
class Media:
    data: bytes
    format: str  # "png"...
    meta: dict
    origin: str


@dataclass
class Anchor:
    offset: int  # char offset into body
    page: int


@dataclass
class Envelope:
    body: str = ""
    tables: list[Table] = field(default_factory=list)
    images: list[Media] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    anchors: list[Anchor] = field(default_factory=list)

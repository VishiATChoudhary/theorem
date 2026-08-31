"""theorem: a graph query and construction language agents can't get wrong.

The whole surface an embedding application needs:

    from theorem import Schema, Session

    with Session("mydb", Schema()) as db:
        print(db.run('derive class supplier from entity with {country: str}'))
        print(db.run('assert supplier {name: "VoltaChem", country: "DE"} as v'))
        print(db.run('find supplier where country = "DE" as s\\nreturn s.name'))

`Schema()` is the base schema: `entity` to derive domain classes from,
plus the document classes the ingest pipeline uses. `Schema.supply_chain()`
adds the demo classes the tutorial is written against.
"""

from .canonical import CanonicalError, canonical
from .engine.executor import ExecError, Limits, limits
from .engine.storage import Store, StoreError, StoreLocked
from .ingest.bulk import LoadError, load_edges, load_nodes
from .parser import ParseError, parse
from .prompt import Answer, agent_prompt, answer, repair_prompt
from .schema import ClassDef, EdgeDef, Schema
from .session import Session
from .verifier import VerifyError, verify

__version__ = "0.3.0"

__all__ = [
    "Answer",
    "CanonicalError",
    "ClassDef",
    "EdgeDef",
    "ExecError",
    "Limits",
    "LoadError",
    "ParseError",
    "Schema",
    "Session",
    "Store",
    "StoreError",
    "StoreLocked",
    "VerifyError",
    "__version__",
    "agent_prompt",
    "answer",
    "canonical",
    "limits",
    "load_edges",
    "load_nodes",
    "parse",
    "repair_prompt",
    "verify",
]

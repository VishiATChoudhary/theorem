# Ingestion + Playbooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any uploaded file becomes queryable graph structure with page provenance; a natural-language playbook compiles (via an agent) into the database's schema.

**Architecture:** Three deterministic-first stages (normalize -> Envelope -> stage into built-in classes -> optional agent extraction emitting theorem programs), plus playbook compilation targeting new `derive` verbs. All agent calls go through a pluggable Runner.

**Tech Stack:** Python 3.11+ stdlib core; optional extras: pdfplumber `[pdf]`, python-docx/openpyxl/python-pptx `[office]`. Agent adapters shell out to `claude`/`codex` CLIs or hit APIs with a user key.

**Spec:** `docs/superpowers/specs/2026-08-28-ingestion-design.md` and `docs/superpowers/specs/2026-08-28-playbook-design.md`

## Global Constraints

- Branch: `demo`. Every task ends green: `uv run pytest -q` and `uvx ruff check src tests eval` and `uvx ruff format --check src tests eval`.
- Core package stays zero-runtime-dependency. Parsers land only behind extras; importing `theorem` must never import an extra.
- No AGPL/RAIL-M dependencies anywhere (no PyMuPDF, no Marker, no MinerU).
- Ingestion structure nodes (document/chunk/media/table rows) are written via `Store.apply`, NOT via `assert` statements: dedup candidates are for entity classes, not structure nodes.
- The name "theorem" is lowercase in all prose/UI.
- No em dashes in any text output.
- Commit after every task with a sign-off-free conventional message ending in `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Out of scope for THIS plan (follow-up plan): VLM OCR routing, image captioning, `[web]`/yaml normalizers, legacy Office, eval-harness Runner migration.

---

### Task 1: Built-in ingestion classes in every schema

**Files:**
- Modify: `src/theorem/schema.py` (Schema.__init__ and supply_chain)
- Test: `tests/test_ingest_schema.py`

**Interfaces:**
- Produces: every `Schema()` instance contains classes `entity {name: str}`, `piece {}` (abstract parent, no props), `document {title: str, mime: str, pages: int, sha256: str}`, `chunk {text: str, page: int, ord: int}`, `media {caption: str, format: str, page: int}` with `chunk`/`media` having `base="piece"`, and edge `part_of(piece: piece, whole: document)`. `supply_chain()`'s `table_blob` gains `base="piece"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingest_schema.py
from theorem.schema import Schema


def test_every_schema_has_ingestion_builtins():
    s = Schema()
    for cls in ("entity", "piece", "document", "chunk", "media"):
        assert cls in s.classes
    assert s.classes["chunk"].base == "piece"
    assert s.classes["media"].base == "piece"
    assert s.edges["part_of"].roles == {"piece": "piece", "whole": "document"}


def test_supply_chain_table_blob_is_a_piece():
    s = Schema.supply_chain()
    assert s.classes["table_blob"].base == "piece"
    assert "entity" in s.classes  # builtins present in derived schemas too
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ingest_schema.py -q`
Expected: FAIL (`entity` not in classes)

- [ ] **Step 3: Implement**

In `src/theorem/schema.py`, Schema is a `@dataclass` with `classes`/`edges` dict fields. Add a `__post_init__` installing builtins (runs for `Schema()` and for `supply_chain()`, which starts from `Schema()`):

```python
def __post_init__(self):
    b = self.classes
    b.setdefault("entity", ClassDef("entity", {"name": "str"}))
    b.setdefault("piece", ClassDef("piece", {}))
    b.setdefault(
        "document",
        ClassDef("document", {"title": "str", "mime": "str", "pages": "int", "sha256": "str"}),
    )
    b.setdefault("chunk", ClassDef("chunk", {"text": "str", "page": "int", "ord": "int"}, base="piece"))
    b.setdefault("media", ClassDef("media", {"caption": "str", "format": "str", "page": "int"}, base="piece"))
    self.edges.setdefault("part_of", EdgeDef("part_of", {"piece": "piece", "whole": "document"}))
```

If Schema is NOT a dataclass (check first), add the same lines at the end of its `__init__`. In `supply_chain()`, change the `table_blob` ClassDef to pass `base="piece"`.

- [ ] **Step 4: Full suite**

Run: `uv run pytest -q`
Expected: all pass (existing schema render tests may need their expected class lists updated; fix them to include builtins, do not weaken assertions).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: built-in ingestion classes (entity, piece, document, chunk, media) in every schema

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `derive edge` verb, end to end

**Files:**
- Modify: `src/theorem/ast_nodes.py`, `src/theorem/parser.py` (parse_derive), `src/theorem/verifier.py` (DeriveClass case area), `src/theorem/engine/writes.py`, `src/theorem/session.py` (_restore_derived_classes)
- Test: `tests/test_derive_edge.py`

**Interfaces:**
- Produces: AST node `DeriveEdge(name: str, roles: dict[str, str])`; statement syntax `derive edge supplied_to(item: part, buyer: supplier)`; durable lineage record `{"kind": "derive_edge", "name": ..., "roles": {...}}`; `Session._restore_derived_classes` renamed `_restore_derived_schema` and also restores edges.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_derive_edge.py
import pytest

from theorem.parser import ParseError, parse
from theorem.schema import Schema
from theorem.session import Session


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def test_derive_edge_creates_usable_edge(sess):
    out = sess.run("derive edge acquired(buyer: supplier, target: supplier)")
    assert "receipt" in out and "acquired" in out
    sess.run('assert supplier {name: "A", country: "DE"} as a')
    sess.run('assert supplier {name: "B", country: "FR"} as b')
    out = sess.run("assert edge acquired(buyer: a, target: b)")
    assert "created edge acquired" in out


def test_derive_edge_unknown_class_rejected(sess):
    out = sess.run("derive edge x(a: nonexistent, b: supplier)")
    assert "nothing was executed" in out


def test_derive_edge_duplicate_rejected(sess):
    sess.run("derive edge acquired(buyer: supplier, target: supplier)")
    out = sess.run("derive edge acquired(buyer: supplier, target: supplier)")
    assert "nothing was executed" in out


def test_derive_edge_survives_restart(tmp_path):
    db = tmp_path / "db"
    s1 = Session(db, Schema.supply_chain())
    s1.run("derive edge acquired(buyer: supplier, target: supplier)")
    s2 = Session(db, Schema.supply_chain())
    assert "acquired" in s2.schema.edges


def test_derive_edge_needs_two_roles():
    with pytest.raises(ParseError):
        parse("derive edge x(a: part)")
```

- [ ] **Step 2: Run, verify FAIL** (`uv run pytest tests/test_derive_edge.py -q`)

- [ ] **Step 3: Implement**

`ast_nodes.py`:

```python
@dataclass
class DeriveEdge(Stmt):
    name: str
    roles: dict[str, str]  # role name -> class name, exactly two
```

`parser.py`, in `parse_derive` (currently expects word `class`): branch on the next word. `derive edge NAME ( role : CLASS , role : CLASS )` reuses the role-list parsing shape from `parse_assert`'s edge branch; enforce exactly two roles with `ParseError` otherwise.

`verifier.py`, new case (import DeriveEdge):

```python
case DeriveEdge(name=name, roles=roles):
    if name in schema.edges:
        raise VerifyError(line, f'edge "{name}" already exists')
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise VerifyError(line, f'edge name "{name}" must be a lowercase identifier')
    if len(roles) != 2:
        raise VerifyError(line, f"edge {name} needs exactly two roles")
    for role, cls in roles.items():
        if cls not in schema.classes:
            raise VerifyError(line, f'unknown class "{cls}".{_suggest(cls, schema.classes)}')
    schema.edges[name] = EdgeDef(name, dict(roles))  # verify-time staging, like DeriveClass
```

(`EdgeDef` imported from `.schema` at top of file.)

`writes.py`: add `_derive_edge(stmt, ctx)` mirroring `_derive`: `store.apply({"op": "lineage", "kind": "derive_edge", "name": stmt.name, "roles": stmt.roles})` FIRST, then `ctx.schema.edges[stmt.name] = EdgeDef(stmt.name, dict(stmt.roles))`, receipt line `f"receipt: edge {stmt.name} declared at @t-{pos}"`. Register in `execute_write`'s dispatch.

`session.py`: rename `_restore_derived_classes` -> `_restore_derived_schema`; in the loop also handle `rec.get("kind") == "derive_edge"`: `self.schema.edges.setdefault(rec["name"], EdgeDef(rec["name"], dict(rec["roles"])))`.

- [ ] **Step 4: Run task tests then full suite; fix; format** (`uvx ruff format src tests`)

- [ ] **Step 5: Commit** (`feat: derive edge verb with durable replay`)

---

### Task 3: Policy clauses on `derive class` (`quota N`, `dedup X`)

**Files:**
- Modify: `src/theorem/ast_nodes.py` (DeriveClass), `src/theorem/parser.py`, `src/theorem/verifier.py`, `src/theorem/engine/writes.py` (_derive), `src/theorem/schema.py` (ClassDef), `src/theorem/engine/dedup.py`, `src/theorem/session.py`
- Test: `tests/test_derive_policies.py`

**Interfaces:**
- Produces: `DeriveClass` gains fields `quota: int | None = None`, `dedup: float | None = None`; `ClassDef` gains `dedup_threshold: float | None = None`; dedup pipeline honors per-class threshold; syntax `derive class competitor from entity with {hq: str} quota 50 dedup 0.9` (clauses optional, in that order).

- [ ] **Step 1: Failing tests**

```python
# tests/test_derive_policies.py
import pytest

from theorem.parser import parse
from theorem.schema import Schema
from theorem.session import Session


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def test_quota_clause_enforced(sess):
    sess.run("derive class widget from entity with {} quota 2")
    sess.run('assert widget {name: "a"} as a')
    sess.run('assert widget {name: "b"} as b')
    out = sess.run('assert widget {name: "c"} as c')
    assert "quota" in out and "error" in out


def test_dedup_clause_sets_threshold(sess):
    sess.run("derive class brand from entity with {} dedup 0.99")
    sess.run('assert brand {name: "Volta Chemical"} as a')
    # 'Volta Chemical' vs 'Volta Chemicals' scores ~0.97: candidate under
    # the global 0.85, NOT under this class's 0.99
    out = sess.run('assert brand {name: "Volta Chemicals"} as b')
    assert "dup candidates" not in out


def test_policy_clauses_survive_restart(tmp_path):
    db = tmp_path / "db"
    s1 = Session(db, Schema.supply_chain())
    s1.run("derive class widget from entity with {} quota 2 dedup 0.95")
    s2 = Session(db, Schema.supply_chain())
    assert s2.schema.classes["widget"].quota == 2
    assert s2.schema.classes["widget"].dedup_threshold == 0.95


def test_default_quota_unchanged(sess):
    sess.run("derive class widget from entity with {}")
    assert sess.schema.classes["widget"].quota == 500
```

Note the prefix-containment boost in `dedup._similarity` lifts near-prefix names to >=0.9; the 0.99 threshold in the second test sits above both paths. If the raw score surprises, print `dedup._similarity("Volta Chemical", "Volta Chemicals")` and pick a threshold above it; do not weaken the assertion shape.

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement**

Parser (`parse_derive`, class branch, after propdecls): loop `while self.at_word("quota") or self.at_word("dedup")`; `quota` -> `self._int(self.next(), "quota", 1)`; `dedup` -> next token must be a float number in (0,1] else ParseError. Verifier: pass `quota`/`dedup` into the staged ClassDef (`quota=stmt.quota or 500`, `dedup_threshold=stmt.dedup`). Writes `_derive`: include `"quota": stmt.quota or PROVISIONAL_QUOTA, "dedup": stmt.dedup` in the lineage record and on the live ClassDef. Session restore: read both (`dedup_threshold=rec.get("dedup")`). Dedup pipeline, in `sync_candidates`/`_candidate`: threshold = `store`-side lookup is not available there, so pass the schema-aware threshold in: `_candidate` gains param `threshold: float = SIM_THRESHOLD`; `writes._assert_node` fetches `ctx.schema.classes[stmt.cls].dedup_threshold or dedup.SIM_THRESHOLD` and passes it through `sync_candidates(store, node, threshold=...)`.

- [ ] **Step 4: Task tests, full suite, ruff**

- [ ] **Step 5: Commit** (`feat: quota and dedup policy clauses on derive class`)

---

### Task 4: Class deprecation status

**Files:**
- Modify: `src/theorem/schema.py` (allowed status values comment), `src/theorem/verifier.py` (AssertNode case), `src/theorem/session.py` (restore), `src/theorem/engine/writes.py`
- Test: `tests/test_deprecation.py`

**Interfaces:**
- Produces: `ClassDef.status` may be `"deprecated"`; verifier rejects `assert` into deprecated classes with message containing "deprecated"; a durable lineage record `{"kind": "deprecate_class", "name": ...}` written by new writes helper `deprecate_class(session, name) -> str` in `src/theorem/engine/writes.py` (plain function, used by playbook recompile in Task 12; not a language verb).

- [ ] **Step 1: Failing tests**

```python
# tests/test_deprecation.py
import pytest

from theorem.engine.writes import deprecate_class
from theorem.schema import Schema
from theorem.session import Session


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def test_deprecated_class_rejects_new_asserts(sess):
    sess.run("derive class widget from entity with {}")
    sess.run('assert widget {name: "a"} as a')
    deprecate_class(sess, "widget")
    out = sess.run('assert widget {name: "b"} as b')
    assert "deprecated" in out and "nothing was executed" in out
    # existing data stays queryable
    out = sess.run("find widget as w\nreturn w.name")
    assert "results: 1 of 1" in out


def test_deprecation_survives_restart(tmp_path):
    db = tmp_path / "db"
    s1 = Session(db, Schema.supply_chain())
    s1.run("derive class widget from entity with {}")
    deprecate_class(s1, "widget")
    s2 = Session(db, Schema.supply_chain())
    assert s2.schema.classes["widget"].status == "deprecated"
```

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement**

`writes.py`:

```python
def deprecate_class(session, name: str) -> str:
    cdef = session.schema.classes[name]
    pos = session.store.apply({"op": "lineage", "kind": "deprecate_class", "name": name})
    cdef.status = "deprecated"
    return f"receipt: class {name} deprecated at @t-{pos}; existing nodes kept, new asserts rejected"
```

Verifier AssertNode case, first line after `_check_class`: `if schema.classes[cls].status == "deprecated": raise VerifyError(line, f'class "{cls}" is deprecated (playbook change); existing data remains queryable')`. Session restore loop: `kind == "deprecate_class"` -> set status if class present.

- [ ] **Step 4: Tests, suite, ruff** | **Step 5: Commit** (`feat: class deprecation`)

---

### Task 5: Envelope + stdlib type sniffing

**Files:**
- Create: `src/theorem/ingest/__init__.py`, `src/theorem/ingest/envelope.py`, `src/theorem/ingest/sniff.py`
- Test: `tests/test_sniff.py`

**Interfaces:**
- Produces:

```python
# envelope.py
@dataclass
class Table:
    name: str
    rows: list[dict[str, str]]
    origin: str  # "page 3" / "sheet Sales" / "slide 2"

@dataclass
class Media:
    data: bytes
    format: str   # "png"...
    meta: dict
    origin: str

@dataclass
class Anchor:
    offset: int   # char offset into body
    page: int

@dataclass
class Envelope:
    body: str = ""
    tables: list[Table] = field(default_factory=list)
    images: list[Media] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    anchors: list[Anchor] = field(default_factory=list)

# sniff.py
def sniff(data: bytes, filename: str = "") -> str  # returns one of:
# "pdf" "docx" "xlsx" "pptx" "zip" "png" "jpeg" "webp" "gif"
# "csv" "json" "jsonl" "markdown" "text" "binary"
```

- [ ] **Step 1: Failing tests**

```python
# tests/test_sniff.py
import io
import zipfile

from theorem.ingest.sniff import sniff


def _zip_with(entry: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(entry, "x")
    return buf.getvalue()


def test_magic_bytes():
    assert sniff(b"%PDF-1.7 ...") == "pdf"
    assert sniff(b"\x89PNG\r\n\x1a\n rest") == "png"
    assert sniff(b"\xff\xd8\xff\xe0 rest") == "jpeg"
    assert sniff(b"RIFF1234WEBPVP8 ") == "webp"


def test_ooxml_disambiguation():
    assert sniff(_zip_with("word/document.xml")) == "docx"
    assert sniff(_zip_with("xl/workbook.xml")) == "xlsx"
    assert sniff(_zip_with("ppt/presentation.xml")) == "pptx"
    assert sniff(_zip_with("random.txt")) == "zip"


def test_text_kinds():
    assert sniff(b'{"a": 1}') == "json"
    assert sniff(b'{"a": 1}\n{"a": 2}\n') == "jsonl"
    assert sniff(b"# Title\n\nprose", "notes.md") == "markdown"
    assert sniff(b"a,b\n1,2\n", "d.csv") == "csv"
    assert sniff(b"plain words") == "text"
    assert sniff(b"\x00\x01\x02") == "binary"


def test_extension_never_overrides_content():
    assert sniff(b"%PDF-1.7", "malicious.csv") == "pdf"
```

- [ ] **Step 2: Run, verify FAIL** (module missing)

- [ ] **Step 3: Implement**

`sniff.py` logic order: magic bytes (`%PDF`, PNG, `\xff\xd8\xff`, `RIFF....WEBP`, `GIF8`, `PK\x03\x04`); for zip, open with `zipfile.ZipFile(io.BytesIO(data))` and check namelist prefixes `word/`, `xl/`, `ppt/`; then try utf-8 decode (errors -> "binary"); for text: whole-body `json.loads` ok -> "json"; every non-empty line `json.loads` ok and >1 line -> "jsonl"; filename endswith .md or first char `#` -> "markdown"; filename endswith .csv or (>=2 lines agreeing on comma count >=1 via `csv.Sniffer` try) -> "csv"; else "text". Filename is a hint only inside the text branch; magic always wins (last test).

- [ ] **Step 4: Tests, suite, ruff** | **Step 5: Commit** (`feat: ingest envelope types and stdlib type sniffing`)

---

### Task 6: Stdlib normalizers (txt/md/csv/json/jsonl) + dispatch

**Files:**
- Create: `src/theorem/ingest/normalize.py`
- Test: `tests/test_normalize_stdlib.py`

**Interfaces:**
- Consumes: `sniff`, `Envelope`, `Table`
- Produces: `normalize(data: bytes, filename: str) -> Envelope`. Raises `IngestError(Exception)` (defined in `normalize.py`) for "binary"/"zip" and for extras-missing formats with an install hint.

- [ ] **Step 1: Failing tests**

```python
# tests/test_normalize_stdlib.py
import pytest

from theorem.ingest.normalize import IngestError, normalize


def test_markdown_passthrough():
    env = normalize(b"# T\n\nbody text", "n.md")
    assert env.body.startswith("# T")
    assert env.meta["format"] == "markdown"


def test_csv_becomes_table_not_body():
    env = normalize(b"name,cost\nbolt,1.0\n", "parts.csv")
    assert env.body == ""
    assert env.tables[0].rows == [{"name": "bolt", "cost": "1.0"}]
    assert env.tables[0].name == "parts"


def test_homogeneous_json_array_becomes_table():
    env = normalize(b'[{"a": "1"}, {"a": "2"}]', "d.json")
    assert len(env.tables[0].rows) == 2


def test_hetero_json_stays_body():
    env = normalize(b'{"a": {"b": 1}}', "d.json")
    assert "```json" in env.body


def test_jsonl_becomes_table_with_union_columns():
    env = normalize(b'{"a": "1"}\n{"b": "2"}\n', "d.jsonl")
    assert set(env.tables[0].rows[1].keys()) == {"a", "b"}


def test_binary_rejected():
    with pytest.raises(IngestError):
        normalize(b"\x00\x01", "blob.bin")


def test_pdf_without_extra_names_the_extra():
    with pytest.raises(IngestError, match=r"theorem\[pdf\]"):
        normalize(b"%PDF-1.7", "d.pdf")
```

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement**

`normalize()` dispatches on `sniff()`. markdown/text: body = decoded text, `meta={"format": kind, "filename": filename}`. csv: `csv.DictReader` over decoded text -> one Table named `Path(filename).stem`. json: `json.loads`; if list of dicts with all-identical-or-overlapping str keys -> Table (values stringified via `str()`), else body = f"```json\n{pretty}\n```". jsonl: per-line loads, union of keys, missing values "" (empty string, matching the str-typed Table contract). pdf/docx/xlsx/pptx: try importing the parser inside the branch; on ImportError raise `IngestError(f"...install theorem[pdf] / theorem[office]")`; actual pdf/office implementations arrive Tasks 8/9 in this same function. png/jpeg/webp/gif: Envelope with one Media (meta from bytes length only for now), body "". binary/zip: IngestError.

- [ ] **Step 4: Tests, suite, ruff** | **Step 5: Commit** (`feat: stdlib normalizers with dispatch`)

---

### Task 7: Chunker + stage()

**Files:**
- Create: `src/theorem/ingest/chunk.py`, `src/theorem/ingest/stage.py`
- Test: `tests/test_stage.py`

**Interfaces:**
- Consumes: `Envelope`, `Session`, `Store.apply`, `count_tokens` from `theorem.engine.executor`
- Produces:
  - `chunk.split(body: str, anchors: list[Anchor]) -> list[tuple[str, int]]` (text, page): split on markdown headings first, pack paragraphs, hard cap 600 tokens per chunk, no overlap; page = page of the chunk's first char via anchors (page 0 when no anchors).
  - `stage.stage(session, envelope, filename: str, raw: bytes) -> StageReceipt` with `StageReceipt(doc_id: str, chunks: int, tables: int, media: int, existing: bool, lines: list[str])` and `render()` method. sha256 computed over `raw`; if a document node with that sha256 exists, return `existing=True` with zero new nodes. Structure nodes written via `store.apply` (`put_node`/`put_edge` records, ids from `store.next_id`), each chunk/table/media getting a `part_of` edge to the document node and `props["_source"] = f"doc:{filename}#p{page}"`. Tables are written into `<db>/attachments/<doc-sha8>-<tablename>.csv` and become `table_blob` nodes with `payload` = `attach:` ref and parsed `_rows` (mirror what `writes._assert_node` stores for attach payloads: check it and store the same shape so `refine` works).

- [ ] **Step 1: Failing tests**

```python
# tests/test_stage.py
import pytest

from theorem.ingest.chunk import split
from theorem.ingest.normalize import normalize
from theorem.ingest.stage import stage
from theorem.schema import Schema
from theorem.session import Session


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def test_split_respects_headings_and_cap():
    body = "# A\n" + ("word " * 700) + "\n# B\nshort"
    chunks = split(body, [])
    assert len(chunks) >= 3  # A splits by cap, B separate
    from theorem.engine.executor import count_tokens
    assert all(count_tokens(t) <= 600 for t, _ in chunks)


def test_stage_document_and_chunks(sess):
    raw = b"# Title\n\nHello graph world.\n\n# Part two\n\nMore text."
    env = normalize(raw, "notes.md")
    r = stage(sess, env, "notes.md", raw)
    assert not r.existing and r.chunks >= 2
    out = sess.run("find chunk as c\nfollow c part_of whole as d\nreturn d.title")
    assert "notes.md" in out


def test_stage_sha_dedup(sess):
    raw = b"# Same\ncontent"
    env = normalize(raw, "a.md")
    r1 = stage(sess, env, "a.md", raw)
    r2 = stage(sess, env, "a.md", raw)
    assert r2.existing and r2.doc_id == r1.doc_id


def test_staged_table_is_refinable(sess):
    raw = b"name,unit_cost\nbolt,1.0\n"
    env = normalize(raw, "parts.csv")
    r = stage(sess, env, "parts.csv", raw)
    out = sess.run(
        f'refine {r.doc_table_ids[0]} into part with '
        f'{{name: col "name", unit_cost: col "unit_cost"}} as np'
    )
    assert "refined" in out
```

(Add `doc_table_ids: list[str]` to StageReceipt for the last test.)

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement**

`split()`: segment body at lines matching `^#{1,6} `; within each segment, accumulate paragraphs (`\n\n` splits) into a buffer, flush when `count_tokens(buffer + para) > 600`; a single paragraph over the cap is hard-cut at 2400-char boundaries. Page lookup: binary search anchors for the chunk's start offset.

`stage()`: read `writes._load_attachment` and `writes._assert_node` FIRST to copy the exact `_rows`/`payload` prop shape for table blobs. Apply order: document node, then per piece (chunk/table/media) node + `put_edge` for `part_of`. sha lookup: scan `store.nodes.values()` for `cls == "document" and props.get("sha256") == digest`.

- [ ] **Step 4: Tests, suite, ruff** | **Step 5: Commit** (`feat: chunker and deterministic staging with sha dedup and provenance`)

---

### Task 8: PDF normalizer (`[pdf]` extra)

**Files:**
- Modify: `src/theorem/ingest/normalize.py` (pdf branch), `pyproject.toml`
- Test: `tests/test_normalize_pdf.py`

**Interfaces:**
- Consumes: pdfplumber (extra)
- Produces: pdf branch fills body (page texts joined with `\n\n`, heading heuristics NOT attempted), one Anchor per page start, `extract_tables()` per page -> Table objects (`origin=f"page {n}"`, first row as header), `meta["pages"]`.

- [ ] **Step 1: Add the extra**

`pyproject.toml`:

```toml
[project.optional-dependencies]
pdf = ["pdfplumber>=0.11"]
office = ["python-docx>=1.1", "openpyxl>=3.1", "python-pptx>=1.0"]
```

Run `uv sync --extra pdf`.

- [ ] **Step 2: Failing test** (generate a fixture PDF with pdfplumber's dependency-free sibling: build via reportlab? NO, keep zero test deps: create the fixture with pdfplumber unavailable? pdfplumber cannot write PDFs). Write the fixture by hand: a minimal one-page text PDF checked into `tests/fixtures/mini.pdf` generated ONCE via `uv run python -c` using pdfplumber's bundled pdfminer? pdfminer cannot write either. Resolution: construct the fixture with stdlib only, a hand-written minimal PDF is error-prone, so generate it in-test with the tiny known-good byte template below (valid single-page PDF with text "Hello theorem", widely used minimal example):

```python
# tests/test_normalize_pdf.py
import pytest

pdfplumber = pytest.importorskip("pdfplumber")

from theorem.ingest.normalize import normalize

MINI_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 60>>stream\nBT /F1 18 Tf 20 100 Td (Hello theorem) Tj ET\nendstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>"
)


def test_pdf_text_and_pages():
    env = normalize(MINI_PDF, "mini.pdf")
    assert "Hello theorem" in env.body
    assert env.meta["pages"] == 1
    assert env.anchors and env.anchors[0].page == 1
```

If pdfplumber rejects the handcrafted bytes (no xref), fall back in Step 3 to writing `tests/fixtures/mini.pdf` once with `uv run python tests/fixtures/make_mini_pdf.py` where the script uses `zlib`-free raw PDF with a proper xref table (script checked in; fixture checked in; both tiny). The assertion set stays identical.

- [ ] **Step 3: Implement the pdf branch**

```python
elif kind == "pdf":
    try:
        import pdfplumber
    except ImportError as e:
        raise IngestError("PDF support needs: pip install theorem[pdf]") from e
    env = Envelope(meta={"format": "pdf", "filename": filename})
    parts: list[str] = []
    offset = 0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        env.meta["pages"] = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            env.anchors.append(Anchor(offset=offset, page=i))
            text = page.extract_text() or ""
            parts.append(text)
            offset += len(text) + 2
            for t_i, rows in enumerate(page.extract_tables()):
                if not rows or not rows[0]:
                    continue
                header = [str(h or f"col{j}") for j, h in enumerate(rows[0])]
                dict_rows = [
                    {header[j]: str(c or "") for j, c in enumerate(r)}
                    for r in rows[1:]
                ]
                env.tables.append(
                    Table(name=f"p{i}t{t_i}", rows=dict_rows, origin=f"page {i}")
                )
    env.body = "\n\n".join(parts)
    return env
```

- [ ] **Step 4: `uv run pytest tests/test_normalize_pdf.py -q` then full suite (test auto-skips where extra missing), ruff**

- [ ] **Step 5: Commit** (`feat: PDF normalization via pdfplumber extra`)

---

### Task 9: Office normalizers (`[office]` extra)

**Files:**
- Modify: `src/theorem/ingest/normalize.py`
- Test: `tests/test_normalize_office.py`

**Interfaces:**
- Produces: docx branch (headings -> `#`-prefixed lines by style name "Heading N", paragraphs, `doc.tables` -> Table, inline images -> Media via `doc.part.rels` blobs); xlsx branch (openpyxl `load_workbook(io.BytesIO(data), data_only=True, read_only=True)`, one Table per sheet, first row as header); pptx branch (per slide: shapes with text frames -> markdown section headed `# Slide N`, speaker notes appended, `shape.has_table` -> Table, `PICTURE` shapes -> Media).

- [ ] **Step 1: Failing tests** (fixtures built in-test WITH the same libraries: python-docx/openpyxl/python-pptx can all write; `pytest.importorskip` each)

```python
# tests/test_normalize_office.py
import io

import pytest

from theorem.ingest.normalize import normalize


def test_docx_headings_tables():
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Big Title", level=1)
    d.add_paragraph("Some prose.")
    t = d.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "name", "cost"
    t.rows[1].cells[0].text, t.rows[1].cells[1].text = "bolt", "1.0"
    buf = io.BytesIO(); d.save(buf)
    env = normalize(buf.getvalue(), "r.docx")
    assert "# Big Title" in env.body and "Some prose." in env.body
    assert env.tables[0].rows == [{"name": "bolt", "cost": "1.0"}]


def test_xlsx_sheets_to_tables():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Sales"
    ws.append(["region", "amount"]); ws.append(["EU", 42])
    buf = io.BytesIO(); wb.save(buf)
    env = normalize(buf.getvalue(), "s.xlsx")
    assert env.tables[0].name == "Sales"
    assert env.tables[0].rows == [{"region": "EU", "amount": "42"}]


def test_pptx_slides_and_notes():
    pptx = pytest.importorskip("pptx")
    p = pptx.Presentation()
    slide = p.slides.add_slide(p.slide_layouts[1])
    slide.shapes.title.text = "Pitch"
    slide.placeholders[1].text = "First bullet"
    buf = io.BytesIO(); p.save(buf)
    env = normalize(buf.getvalue(), "d.pptx")
    assert "# Slide 1" in env.body and "Pitch" in env.body
```

- [ ] **Step 2: `uv sync --extra office`, run, verify FAIL**
- [ ] **Step 3: Implement the three branches** (docx interleaved order via iterating `doc.element.body` children, mapping `w:p` -> paragraph, `w:tbl` -> table, the well-known recipe; each branch wrapped in the same ImportError -> IngestError pattern naming `theorem[office]`)
- [ ] **Step 4: Tests, full suite, ruff** | **Step 5: Commit** (`feat: office normalizers docx/xlsx/pptx`)

---

### Task 10: Runner protocol + adapters

**Files:**
- Create: `src/theorem/ingest/runners.py`
- Test: `tests/test_runners.py`

**Interfaces:**
- Produces:

```python
class RunnerError(Exception): ...

class Runner(Protocol):
    def run(self, prompt: str) -> str: ...

@dataclass
class CLIRunner:            # covers claude/codex/copilot/cursor
    argv: list[str]         # e.g. ["claude", "-p"] ; prompt appended as final arg
    timeout: int = 300
    def run(self, prompt: str) -> str: ...  # subprocess.run, check stdout, RunnerError on rc!=0

@dataclass
class APIRunner:
    model: str = "claude-haiku-4-5-20251001"
    def run(self, prompt: str) -> str: ...  # anthropic Messages API via urllib, key from THEOREM_API_KEY

def get_runner(name: str) -> Runner
# "claude"->CLIRunner(["claude","-p"]), "codex"->CLIRunner(["codex","exec"]),
# "copilot"->CLIRunner(["copilot","-p"]), "cursor"->CLIRunner(["cursor-agent","-p"]),
# "api"->APIRunner(); unknown -> RunnerError listing options
```

- [ ] **Step 1: Failing tests**

```python
# tests/test_runners.py
import pytest

from theorem.ingest.runners import CLIRunner, RunnerError, get_runner


def test_cli_runner_captures_stdout():
    r = CLIRunner(argv=["/bin/echo"])
    assert r.run("hello").strip() == "hello"


def test_cli_runner_error_on_failure():
    r = CLIRunner(argv=["/usr/bin/false"])
    with pytest.raises(RunnerError):
        r.run("x")


def test_get_runner_unknown():
    with pytest.raises(RunnerError, match="claude"):
        get_runner("clippy")
```

- [ ] **Step 2: Run, FAIL** | **Step 3: Implement** (subprocess.run(argv + [prompt], capture_output=True, text=True, timeout); APIRunner: `urllib.request` POST to `https://api.anthropic.com/v1/messages` with `x-api-key` from env, `anthropic-version: 2023-06-01`, max_tokens 4096, return first text block; RunnerError if env var missing) | **Step 4: Tests+suite+ruff** | **Step 5: Commit** (`feat: pluggable agent Runner with CLI and API adapters`)

---

### Task 11: Stage-3 extraction

**Files:**
- Create: `src/theorem/ingest/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: Runner, Session, `count_tokens`
- Produces: `extract(session, doc_id: str, runner: Runner, budget: int = 50_000, focus: str = "") -> ExtractReceipt` with fields `chunks_done: int, chunks_failed: int, budget_spent: int, stopped_early: bool, lines: list[str]` and `render()`. Per chunk of the document (found via `part_of` edges, class `chunk`, ordered by `ord`): prompt = header (task instruction + `session.schema.render()` + focus + provenance instruction: every statement must end `source doc:<title>#p<page>`) + chunk text; run; treat output as a theorem program via `session.run`; if output contains "nothing was executed", send ONE repair message (original prompt + program + error text); on second failure `flag` the document node with reason `f"extract failed chunk {ord}"` and count `chunks_failed`. Budget: accumulate `count_tokens(prompt) + count_tokens(output)`; before each chunk, if spent >= budget, set `stopped_early` and stop.

- [ ] **Step 1: Failing tests** (fake runner, no subprocess)

```python
# tests/test_extract.py
import pytest

from theorem.ingest.extract import extract
from theorem.ingest.normalize import normalize
from theorem.ingest.stage import stage
from theorem.schema import Schema
from theorem.session import Session


class ScriptedRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return self.outputs.pop(0)


@pytest.fixture
def staged(tmp_path):
    sess = Session(tmp_path / "db", Schema.supply_chain())
    raw = b"VoltaChem is a supplier based in Germany."
    r = stage(sess, normalize(raw, "note.md"), "note.md", raw)
    return sess, r.doc_id


def test_extract_happy_path(staged):
    sess, doc = staged
    good = 'assert supplier {name: "VoltaChem", country: "DE"} source doc:note.md#p0 as s1'
    r = extract(sess, doc, ScriptedRunner([good]))
    assert r.chunks_done == 1 and r.chunks_failed == 0
    out = sess.run("find supplier as s\nreturn s.name")
    assert "VoltaChem" in out


def test_extract_repair_retry(staged):
    sess, doc = staged
    bad = 'assert supplier {name: "VoltaChem", contry: "DE"} as s1'
    good = 'assert supplier {name: "VoltaChem", country: "DE"} as s1'
    runner = ScriptedRunner([bad, good])
    r = extract(sess, doc, runner)
    assert r.chunks_done == 1
    assert "contry" in runner.prompts[1]  # error fed back


def test_extract_failure_flags_document(staged):
    sess, doc = staged
    bad = "total nonsense ((("
    r = extract(sess, doc, ScriptedRunner([bad, bad]))
    assert r.chunks_failed == 1
    out = sess.run(f"find document as d\nreturn d.query_traffic, d.health")
    assert "query" in out  # flag landed -> health.query nonzero renders


def test_extract_budget_stops(staged):
    sess, doc = staged
    r = extract(sess, doc, ScriptedRunner([]), budget=1)
    assert r.stopped_early and r.chunks_done == 0
```

(For the flag assertion: use `session.run(f'flag {doc} reason ...')`-equivalent via the writes path inside extract; assert instead on `r.lines` containing "flagged" if the health render proves awkward: pick ONE assertion and keep it strict.)

- [ ] **Step 2: Run, FAIL** | **Step 3: Implement** | **Step 4: Tests+suite+ruff** | **Step 5: Commit** (`feat: budgeted agent extraction emitting theorem programs`)

---

### Task 12: Playbook compile

**Files:**
- Create: `src/theorem/ingest/playbook.py`
- Test: `tests/test_playbook.py`

**Interfaces:**
- Consumes: Runner, stage/normalize, `deprecate_class`, Session
- Produces: `compile_playbook(session, path: Path, runner: Runner, unhinged: bool = False, confirm: Callable[[str], bool] = None) -> PlaybookReceipt`. Agent response contract (taught in the prompt): three fenced blocks tagged `theorem`, `summary`, `focus`; parse with a regex over ```` ```<tag>\n...\n``` ````. Flow: stage the playbook file (document node) -> build prompt (playbook text + `schema.render()` + derive grammar + worked example + rule "justify every class with a playbook quote in the summary") -> run -> parse blocks -> `parse()`+`verify()` the program (dry) -> repair retry once on VerifyError -> if not `unhinged`, call `confirm(program + "\n\n" + summary)`; abort with receipt if False -> `session.run(program)` -> store focus: `store.apply({"op": "patch_node", "id": doc_id, "props": {"_focus": focus}})` -> recompile diff: any class previously derived from a playbook (lineage kind `derive_class` with `playbook` key) whose name is absent from the new program and not deprecated -> `deprecate_class`. Receipt lists applied/deprecated/focus.
- Every `derive` lineage record written during apply must carry `"playbook": doc_id`: pass through by appending ` # via playbook` is NOT possible in-language, so `compile_playbook` patches the just-written lineage records: after `session.run(program)`, iterate `store.lineage`, and for records with kind derive_class/derive_edge missing `playbook`, `rec["playbook"] = doc_id` and journal the linkage with one extra `store.apply({"op": "lineage", "kind": "playbook_link", "playbook": doc_id, "names": [...]})` so the link is durable (in-memory patch alone would not survive replay).

- [ ] **Step 1: Failing tests**

```python
# tests/test_playbook.py
import pytest

from theorem.ingest.playbook import compile_playbook
from theorem.schema import Schema
from theorem.session import Session

RESPONSE = """```theorem
derive class competitor from entity with {hq_country: str} quota 50
derive edge competes_with(us: competitor, them: competitor)
```
```summary
competitor: "Companies that compete with us" (quote). competes_with: rivalry link.
```
```focus
Prioritize launch dates. Ignore boilerplate.
```"""


class One:
    def __init__(self, out):
        self.out = out
    def run(self, prompt):
        return self.out


@pytest.fixture
def sess(tmp_path):
    return Session(tmp_path / "db", Schema.supply_chain())


def _pb(tmp_path):
    p = tmp_path / "pb.md"
    p.write_text("# Competitors\nWe track companies that compete with us.")
    return p


def test_guided_applies_on_confirm(sess, tmp_path):
    r = compile_playbook(sess, _pb(tmp_path), One(RESPONSE), confirm=lambda s: True)
    assert "competitor" in sess.schema.classes
    assert "competes_with" in sess.schema.edges
    assert sess.schema.classes["competitor"].quota == 50


def test_guided_abort_on_reject(sess, tmp_path):
    compile_playbook(sess, _pb(tmp_path), One(RESPONSE), confirm=lambda s: False)
    assert "competitor" not in sess.schema.classes


def test_unhinged_skips_confirm(sess, tmp_path):
    called = []
    compile_playbook(sess, _pb(tmp_path), One(RESPONSE), unhinged=True,
                     confirm=lambda s: called.append(1) or True)
    assert "competitor" in sess.schema.classes and not called


def test_recompile_deprecates_removed(sess, tmp_path):
    compile_playbook(sess, _pb(tmp_path), One(RESPONSE), confirm=lambda s: True)
    without_edgeclass = RESPONSE.replace(
        "derive class competitor from entity with {hq_country: str} quota 50\n", ""
    ).replace("us: competitor, them: competitor", "us: supplier, them: supplier")
    compile_playbook(sess, _pb(tmp_path), One(without_edgeclass), confirm=lambda s: True)
    assert sess.schema.classes["competitor"].status == "deprecated"


def test_focus_stored(sess, tmp_path):
    r = compile_playbook(sess, _pb(tmp_path), One(RESPONSE), confirm=lambda s: True)
    node = sess.store.nodes[r.doc_id]
    assert "launch dates" in node.props["_focus"].lower()
```

(Recompile test: second `session.run` of a program containing an existing edge name will verify-fail on the duplicate `competes_with`: the `.replace` renames its roles but not the edge; ALSO rename the edge to `rivals_with` in `without_edgeclass` so the program verifies. Adjust the replace accordingly when writing the test.)

- [ ] **Step 2: Run, FAIL** | **Step 3: Implement** | **Step 4: Tests+suite+ruff** | **Step 5: Commit** (`feat: playbook compilation with guided and unhinged modes`)

---

### Task 13: CLI subcommands

**Files:**
- Modify: `src/theorem/cli.py`
- Test: `tests/test_cli_ingest.py`

**Interfaces:**
- Produces: `theorem ingest <file> --db D [--extract] [--agent claude] [--budget 50000]` (normalize+stage, print StageReceipt.render(); with `--extract` run extraction after); `theorem playbook compile <file.md> --db D [--agent claude] [--unhinged]` (guided confirm = stdin `input("apply? [y/N] ")`). Legacy invocations (`theorem prog.thm`, `theorem --repl`) unchanged: dispatch on `argv[0] in ("ingest", "playbook")` before the legacy parser.

- [ ] **Step 1: Failing test**

```python
# tests/test_cli_ingest.py
from theorem.cli import main


def test_cli_ingest_stages_file(tmp_path, capsys):
    f = tmp_path / "n.md"
    f.write_text("# T\n\nsome text")
    rc = main(["ingest", str(f), "--db", str(tmp_path / "db")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "document" in out and "chunk" in out


def test_cli_legacy_repl_flag_still_parses(tmp_path):
    # legacy path: running a program file
    p = tmp_path / "p.thm"
    p.write_text("schema")
    assert main([str(p), "--db", str(tmp_path / "db")]) == 0
```

- [ ] **Step 2: Run, FAIL** | **Step 3: Implement** (subparser-style manual dispatch; ingest reads bytes, calls normalize/stage, prints render; --extract wires `get_runner(args.agent)`) | **Step 4: Tests+suite+ruff** | **Step 5: Commit** (`feat: theorem ingest and theorem playbook CLI subcommands`)

---

### Task 14: Demo UI wiring

**Files:**
- Modify: `demo/upload_server.py`
- Test: `tests/test_upload_server.py` (new; handler functions called directly are awkward, so test via `http.client` against a served instance on an ephemeral port in a thread)

**Interfaces:**
- Produces: POST `/upload` now runs normalize+stage (falls back to old raw-file storage for `IngestError` formats) and returns `{stored, receipt, doc_id, chunks, tables, media, existing}`; POST `/extract?doc=<id>&agent=claude` runs extraction, returns `ExtractReceipt` fields; POST `/playbook?agent=claude&unhinged=0|1` with markdown body compiles (guided mode returns `{proposal: ...}` and a second call `/playbook/apply` with `{token}` applies it; keep a module-level `pending: dict[str, str]` of proposal-token -> program); page gains an uploads list rendered from `/files` on load, per-CSV/document "extract" button, and a playbook textarea pane with Propose/Apply/Unhinged buttons.

- [ ] **Step 1: Failing test**

```python
# tests/test_upload_server.py
import http.client
import json
import threading

import pytest

from demo.upload_server import make_server  # refactor main() to expose make_server(db, port=0)


@pytest.fixture
def server(tmp_path):
    srv = make_server(tmp_path / "db", port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


def test_upload_stages_markdown(server):
    conn = http.client.HTTPConnection("127.0.0.1", server)
    conn.request("POST", "/upload?name=n.md", body=b"# T\n\nhello world")
    data = json.loads(conn.getresponse().read())
    assert data["chunks"] >= 1 and data["existing"] is False


def test_reupload_reports_existing(server):
    conn = http.client.HTTPConnection("127.0.0.1", server)
    for _ in range(2):
        conn.request("POST", "/upload?name=n.md", body=b"# Same\nbody")
        data = json.loads(conn.getresponse().read())
    assert data["existing"] is True
```

- [ ] **Step 2: Run, FAIL** (make_server missing) | **Step 3: Implement** (extract `make_server(db, port) -> HTTPServer` from `main()`; port 0 = ephemeral; wire endpoints; extend PAGE with the list + buttons + playbook pane, same styling) | **Step 4: Tests+suite+ruff** | **Step 5: Commit** (`feat: demo UI stages uploads, extract button, playbook pane`)

---

### Task 15: Spec/docs sync + final green

**Files:**
- Modify: `README.md` (one paragraph + example under a new "Ingest anything" heading on the demo branch), `docs/superpowers/specs/2026-08-28-ingestion-design.md` and `2026-08-28-playbook-design.md` (status: implemented, note deviations if any)

- [ ] **Step 1: Full suite + ruff both checks + `uv run pytest -q` with extras installed (`uv sync --all-extras`)**
- [ ] **Step 2: Manual smoke:** `uv run python demo/upload_server.py --db /tmp/smoke-db`, upload a PDF and a markdown file in the browser, run one extract with `--agent claude` available, screenshot-check the receipts render.
- [ ] **Step 3: Update docs, commit** (`docs: mark ingestion and playbook specs implemented`), push `demo`.

---

## Self-Review (done at write time)

- Spec coverage: normalize (T5/6/8/9), stage+sha-dedup+provenance+part_of (T1/T7), Runner (T10), extract with budget/flags/focus (T11), playbook compile/guided/unhinged/recompile-deprecation/lineage (T2/3/4/12), CLI (T13), UI (T14), monorepo layout respected. Deferred per Global Constraints: VLM OCR, captioning, web/yaml, legacy office.
- Placeholder scan: office task Step 3 names the exact recipe but not full code; acceptable density given tests fully specify behavior. No TBDs.
- Type consistency: StageReceipt fields used in T14 match T7 (`doc_id`, `chunks`, `existing`); Runner protocol consistent T10-T12; `deprecate_class(session, name)` consistent T4/T12.

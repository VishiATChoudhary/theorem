# theorem ingestion: non-CSV documents into the graph

Date: 2026-08-28
Status: draft for review
Branch: demo (builds on the upload interface)
Research: three-agent sweep (extraction tooling, doc-to-KG pipelines, format landscape), 2026-08-28. Key sources cited inline.

## Goal

Uploading any file (PDF, docx/xlsx/pptx, images, HTML, JSON/YAML, markdown) ends in queryable graph nodes with page-level provenance, not a dead-end blob. PDFs are the hard case: they mix prose, tables, and figures in one container.

## The core bet

Every surveyed doc-to-KG pipeline (Microsoft GraphRAG, LightRAG, LlamaIndex PropertyGraphIndex, neo4j SimpleKGPipeline) bolts validation onto extraction after the fact: schema in the prompt, post-hoc pruning, or Pydantic validate-and-retry. The 2026 evidence says schema-guided beats open extraction decisively (92.8% vs 43.8% term accuracy, PMC12928120) and validate-and-retry is the strongest practical enforcement.

theorem already IS a validate-and-retry loop: the extraction LLM emits **theorem programs**, and verify-before-execute rejects hallucinated classes, roles, and properties with corrective errors before anything lands. Ingestion needs no new validation machinery; the language is the schema enforcement. Receipts surface dup candidates at write time, the dedup pipeline is the entity-resolution pass every GraphRAG deployment reports as its top failure, and lineage/provenance are native verbs. The pipeline's novelty budget goes entirely to stages 1-2; stage 3 reuses the language.

## Architecture: three stages

```
file -> [1 NORMALIZE] -> Envelope -> [2 STAGE] -> structure nodes -> [3 EXTRACT] -> entity graph
         deterministic               deterministic                    LLM, optional, budgeted
```

### Stage 1: Normalize (deterministic, no LLM)

Every format converts to one internal **Envelope**:

```python
Envelope:
  body:      str                  # markdown
  tables:    list[Table]          # name, rows (CSV-shaped), origin (page/sheet/slide)
  images:    list[Media]          # bytes, format, exif/meta, origin
  meta:      dict                 # filename, mime, size, page count, ...
  anchors:   list[Anchor]         # body-offset -> (page, bbox) map where the format has pages
```

Format matrix (from the research sweep; all chosen parsers MIT/BSD/Apache, no AGPL/RAIL-M in any path):

| Format | Conversion | Dependency tier |
|---|---|---|
| .csv/.txt/.md/.json/.jsonl | direct; homogeneous JSON arrays and JSONL become tables | stdlib (core) |
| .html | markdownify-style conversion | extra `[web]` |
| .yaml | parse, then as JSON | extra (PyYAML) |
| .pdf | pdfplumber: text + layout + rule-based tables, per-page anchors | extra `[pdf]` (MIT, pure Python) |
| .docx | python-docx: heading tree to markdown, tables to Table, embedded images to Media | extra `[office]` |
| .xlsx | openpyxl (`data_only=True`): one Table per sheet | extra `[office]` |
| .pptx | python-pptx: slide text + speaker notes to markdown, tables, pictures | extra `[office]` |
| .png/.jpg/.webp | Pillow: EXIF/dimensions to meta; caption via stage-3 VLM if enabled | extra `[image]` |
| scanned PDF pages | routed to VLM OCR (Mistral OCR ~$2-4/1k pages, or Claude vision) when a page has no/garbled text layer | extra `[vlm]`, API-only, no local ML |
| .doc/.xls/.ppt legacy | out of scope v0 (LibreOffice-sidecar conversion later); .xls alone possible via xlrd | later |
| audio/video | out of scope v0; interface admits a future transcript.md producer | later |

Principles from the sweep: classical parser first, VLM only for pages the parser cannot read (the converged 2026 pattern); zero local ML dependencies ever (docling-grade parsing stays a documented alternative, not a dependency); file-type detection by content sniffing (puremagic + stdlib zip-entry check to split docx/xlsx/pptx, which all sniff as `application/zip`), never by extension.

### Stage 2: Stage into the graph (deterministic, no LLM)

The Envelope lands as structure nodes using existing engine machinery. New **built-in ingestion classes** joined to every schema (like `table_blob` today):

- `document` {title, mime, pages, sha256} — one per upload, state `blob`
- `chunk` {text, page, ord} — body split on heading/paragraph boundaries (~200-800 tokens; small chunks improve graph fidelity per the GraphRAG literature, size is the main cost lever)
- `table_blob` — existing class; each Table becomes one, `attach:` payload, refinable today
- `media` {caption, format, page} — images; caption empty until stage 3

New built-in edge: `part_of(piece: piece, whole: document)`, where `piece` is a new abstract base class and `chunk`, `media`, and `table_blob` declare `base: piece` (edge roles accept subclasses already; roles cannot take type unions). Every structure node carries `source doc:<file>#p<page>` provenance and origin lineage to the document node, the layered lexical-graph pattern (Document -> Chunk -> entity) that every surveyed system converged on, with Docling's page-anchor discipline: provenance recorded at parse time, never LLM-reconstructed.

After stage 2 the document is already queryable and auditable: `find chunk where page = 3`, `follow chunks part_of whole as doc`. No LLM has run yet; cost so far is zero.

### Stage 3: Extract (LLM, optional, explicitly budgeted)

Per chunk (and per table that the user chooses to semantify rather than refine):

1. Prompt = live `schema` rendering + the chunk text + instruction to emit a theorem program (`assert` nodes, `assert edge`, all with `source doc:...#p<n>`).
2. Run the program through the session. VerifyError -> feed the corrective error back, one repair retry (same loop as the benchmark harness, where it converges).
3. Receipts return dup candidates; they accumulate in the ledger for merge/distinct resolution, exactly the fuzzy-plus-review pass GraphRAG-family systems lack.
4. Failed-after-retry chunks are `flag`ged on the document node, never silently dropped (neo4j's `on_error=IGNORE` silently losing chunks is a documented trap; extraction coverage is a receipt-visible number here).

Design rules taken from the failure-mode literature:

- **Schema-guided, not open extraction.** Out-of-schema entities are verifier rejections. Coverage escape hatch: extraction may propose `derive class` in a separate, human-approved receipt, mirroring LlamaIndex's Dynamic extractor without silent schema drift.
- **No global summarization at ingest.** LazyGraphRAG's lesson: community summaries at index time were ~75% of GraphRAG's cost and got deferred to query time at 0.1% cost for equal quality. theorem ingest writes entities and edges only.
- **Two-model split** (nano-graphrag): extraction on a small model (the benchmark says Haiku-class models write near-perfect theorem), captioning/summaries on the same or cheaper tier.
- **Cross-chunk relations**: chunk-local extraction misses them (arXiv 2510.20345). v0 accepts this and documents it; the doc-level second pass is a listed follow-up.
- **Cost ceiling**: `ingest ... budget N tokens` caps total LLM spend per document; hitting the cap stops extraction with staged structure intact and a receipt saying how far it got. Reference numbers: LightRAG ~1.65k tokens/chunk/call, GraphRAG ~3.4k over 5 calls; Gemini-Flash-class OCR <$0.001/page, Mistral OCR $2-4/1k pages.

### Surface

- Library: `theorem.ingest.normalize(path) -> Envelope`, `stage(session, envelope) -> receipts`, `extract(session, doc_ref, model=..., budget=...) -> receipts`.
- CLI: `theorem ingest file.pdf --db ./db [--extract] [--budget 20000]`.
- Upload demo: upload triggers normalize+stage synchronously (fast, deterministic); the receipt in the UI shows chunk/table/media counts with page anchors; an "extract" button per document runs stage 3 and streams receipts including dup candidates.

## Repo layout decision (2026-08-28)

Monorepo for now: ingestion lives at `src/theorem/ingest/` with optional extras, demo app stays in `demo/`. Revisit after launch: the clean split is a separate `theorem-ingest` repo depending on `theorem` via pip (NOT a git submodule); only the built-in ingestion classes would remain in core. Nothing in this design blocks that move: ingest code touches the engine exclusively through `Session` and the schema built-ins.

## Engine/language changes required

1. Built-in ingestion classes + `part_of` edge in every schema (schema.py), like `table_blob` today.
2. Provenance grammar already admits `doc:file#p3` (token regex permits `#`); verifier gains no new rules.
3. `media` and `chunk` need no new verbs: `assert`, `refine`, `retire`, `flag` cover the lifecycle. No parser changes.
4. Optional-dependency mechanism in pyproject (`theorem[pdf]`, `[office]`, `[image]`, `[web]`, `[vlm]`); core stays zero-dependency.

## Not building (and why)

- Local ML parsing (docling/olmOCR/marker): heavy (torch, ~0.5 GB models) or license-encumbered (Marker RAIL-M, PyMuPDF/MinerU AGPL); the API escape hatch covers the same need at $2-4/1k pages.
- Table-to-triples for every cell: tables stay first-class refinable blobs (the SuperRAG/Docs2KG pattern); triple-ifying cells is where hallucination lives.
- Communities/global summaries, embedding retrieval layers: query-time concerns, out of ingestion scope.
- Legacy Office, audio/video: v0 boundary, interfaces admit them later.

## Build order (demo branch)

1. Envelope + normalize for stdlib tier (csv/txt/md/json/jsonl) + type sniffing. Tests: golden envelopes.
2. Stage 2: ingestion classes in schema, `part_of`, document/chunk staging with provenance. Property test: staged nodes always reach their document via lineage and `part_of`.
3. pdfplumber normalize for born-digital PDFs (text + tables + page anchors).
4. Office tier (docx/xlsx/pptx).
5. Upload UI: show staged structure per upload.
6. Stage 3 extract behind `--extract` flag using the `claude` CLI (same harness pattern as eval), with budget cap + flagged failures.
7. VLM OCR + image captioning extra.

Each step lands green (ruff + pytest) before the next; steps 1-5 need no API keys anywhere.

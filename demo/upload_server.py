"""Minimal upload interface for theorem.

Run:  uv run python demo/upload_server.py  [--db ./demo-db] [--port 8765]

Serves a single-page uploader on http://127.0.0.1:8765. Uploads are normalized
and staged into the engine (document/chunk/table_blob/media nodes); formats
that cannot be normalized (binary, zip, or ones missing an optional extra)
fall back to the old raw-file storage path so nothing breaks. Each staged
document can be extracted with an agent runner from the page, and playbooks
(natural-language use cases) can be proposed and applied from a pane on the
same page.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from theorem.ingest.extract import extract
from theorem.ingest.normalize import IngestError, normalize
from theorem.ingest.playbook import BLOCK_RE, compile_playbook
from theorem.ingest.runners import RunnerError, get_runner
from theorem.ingest.stage import stage
from theorem.parser import ParseError
from theorem.schema import Schema
from theorem.session import Session
from theorem.verifier import VerifyError

MAX_BYTES = 50 * 1024 * 1024  # 50 MB per file

# proposal-token -> the agent's raw output (theorem/summary/focus blocks),
# captured on /playbook and replayed unchanged on /playbook/apply so the
# applied program always matches what the user was shown.
pending: dict[str, str] = {}

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>theorem · upload</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: ui-sans-serif, system-ui, sans-serif; max-width: 640px;
         margin: 3rem auto; padding: 0 1rem; }
  h1 { font-family: Iowan Old Style, Palatino, Georgia, serif;
       font-weight: 600; font-size: 1.6rem; }
  h1 .dot { color: #7c5cff; }
  h2 { font-size: 1rem; margin-top: 2.5rem; }
  #drop { border: 2px dashed #7c5cff88; border-radius: 12px; padding: 3rem 1rem;
          text-align: center; cursor: pointer; transition: background .15s; }
  #drop.hover { background: #7c5cff22; }
  #drop input { display: none; }
  ul { list-style: none; padding: 0; }
  li { padding: .6rem .8rem; margin: .4rem 0; border-radius: 8px;
       background: #7c5cff11; font-size: .9rem; }
  li b { font-weight: 600; }
  li button { margin-left: .5rem; font-size: .8rem; }
  pre { margin: .4rem 0 0; font-size: .75rem; white-space: pre-wrap;
        opacity: .75; }
  .err { background: #ff5c5c22; }
  textarea { width: 100%; min-height: 8rem; font-family: ui-monospace, monospace;
             font-size: .85rem; box-sizing: border-box; }
  .row { display: flex; gap: .5rem; margin-top: .5rem; }
</style>
</head>
<body>
<h1>theorem<span class="dot">.</span> upload</h1>
<div id="drop">
  drop files here or click to choose
  <input type="file" id="file" multiple>
</div>
<ul id="list"></ul>

<h2>playbook</h2>
<textarea id="playbook-text" placeholder="Describe what to extract, e.g. companies that compete with us, their products, and pricing."></textarea>
<div class="row">
  <button id="propose">Propose</button>
  <button id="unhinged">Unhinged apply</button>
</div>
<div id="playbook-result"></div>

<script>
const drop = document.getElementById('drop');
const input = document.getElementById('file');
const list = document.getElementById('list');
const docIds = {};

drop.addEventListener('click', () => input.click());
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('hover'); });
drop.addEventListener('dragleave', () => drop.classList.remove('hover'));
drop.addEventListener('drop', e => {
  e.preventDefault(); drop.classList.remove('hover');
  upload(e.dataTransfer.files);
});
input.addEventListener('change', () => upload(input.files));

function addItem(name) {
  const li = document.createElement('li');
  li.innerHTML = `<b>${name}</b> … uploading`;
  list.prepend(li);
  return li;
}

async function upload(files) {
  for (const f of files) {
    const li = addItem(f.name);
    try {
      const res = await fetch('/upload?name=' + encodeURIComponent(f.name),
                              { method: 'POST', body: f });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      renderStored(li, f.name, data);
    } catch (err) {
      li.classList.add('err');
      li.innerHTML = `<b>${f.name}</b> failed: ${err.message}`;
    }
  }
}

function renderStored(li, name, data) {
  let extra = `<pre>${data.receipt}</pre>`;
  if (data.doc_id) {
    docIds[name] = data.doc_id;
    extra += `<div><button data-name="${name}" class="extract">extract</button></div>`;
  }
  li.innerHTML = `<b>${name}</b> (${data.stored}) stored` + extra;
  const btn = li.querySelector('.extract');
  if (btn) btn.addEventListener('click', () => runExtract(name, li));
}

async function runExtract(name, li) {
  const docId = docIds[name];
  const res = await fetch(`/extract?doc=${encodeURIComponent(docId)}&agent=claude`,
                          { method: 'POST' });
  const data = await res.json();
  const pre = document.createElement('pre');
  pre.textContent = res.ok
    ? `extracted ${data.chunks_done}/${data.chunks_done + data.chunks_failed} chunks`
    : (data.error || res.statusText);
  li.appendChild(pre);
}

async function refresh() {
  const res = await fetch('/files');
  const data = await res.json();
  document.title = `theorem · upload (${data.files.length})`;
  for (const name of data.files) {
    if (!list.querySelector(`[data-file="${name}"]`)) {
      const li = document.createElement('li');
      li.dataset.file = name;
      li.innerHTML = `<b>${name}</b>`;
      list.appendChild(li);
    }
  }
}
refresh();

const playbookText = document.getElementById('playbook-text');
const playbookResult = document.getElementById('playbook-result');

document.getElementById('propose').addEventListener('click', async () => {
  const res = await fetch('/playbook?agent=claude&unhinged=0',
                          { method: 'POST', body: playbookText.value });
  const data = await res.json();
  if (!res.ok) { playbookResult.textContent = data.error || res.statusText; return; }
  playbookResult.innerHTML = `<pre>${data.proposal.program}\n\n${data.proposal.summary}</pre>`
    + `<button id="apply">Apply</button>`;
  document.getElementById('apply').addEventListener('click', async () => {
    const r = await fetch('/playbook/apply', {
      method: 'POST',
      body: JSON.stringify({ token: data.token }),
    });
    const applied = await r.json();
    playbookResult.innerHTML = r.ok
      ? `<pre>applied: ${applied.applied.join(', ')}</pre>`
      : (applied.error || r.statusText);
  });
});

document.getElementById('unhinged').addEventListener('click', async () => {
  const res = await fetch('/playbook?agent=claude&unhinged=1',
                          { method: 'POST', body: playbookText.value });
  const data = await res.json();
  playbookResult.innerHTML = res.ok
    ? `<pre>applied: ${data.applied.join(', ')}</pre>`
    : (data.error || res.statusText);
});
</script>
</body>
</html>
"""


def sanitize(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name.lstrip(".") or "unnamed"


class _CapturingRunner:
    """Wraps a runner, remembering its last raw output."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.output: str = ""

    def run(self, prompt: str) -> str:
        self.output = self.inner.run(prompt)
        return self.output


class _ReplayRunner:
    """Returns a fixed captured output regardless of prompt, so applying a
    previously proposed playbook never re-invokes the agent."""

    def __init__(self, output: str) -> None:
        self.output = output

    def run(self, prompt: str) -> str:
        return self.output


class Handler(BaseHTTPRequestHandler):
    session: Session
    files_dir: Path
    attach_dir: Path
    playbook_dir: Path

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/files":
            names = sorted(p.name for p in self.files_dir.iterdir() if p.is_file())
            self._json(200, {"files": names})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/upload":
            self._handle_upload()
        elif path == "/extract":
            self._handle_extract()
        elif path == "/playbook":
            self._handle_playbook()
        elif path == "/playbook/apply":
            self._handle_playbook_apply()
        else:
            self._json(404, {"error": "not found"})

    def _handle_upload(self) -> None:
        url = urlparse(self.path)
        raw_name = parse_qs(url.query).get("name", ["unnamed"])[0]
        name = sanitize(raw_name)
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"error": "empty upload"})
            return
        if length > MAX_BYTES:
            self._json(413, {"error": f"file exceeds {MAX_BYTES // 1024 // 1024} MB"})
            return
        dest = self.files_dir / name
        stem = dest.stem
        counter = 1
        while dest.exists():  # never overwrite an earlier upload
            dest = self.files_dir / f"{stem}-{counter}{dest.suffix}"
            counter += 1
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = self.rfile.read(min(remaining, 1 << 16))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        dest.write_bytes(raw)

        try:
            envelope = normalize(raw, dest.name)
        except IngestError:
            self._json(200, self._raw_fallback(dest, raw))
            return

        stage_receipt = stage(self.session, envelope, dest.name, raw)
        self._json(
            200,
            {
                "stored": dest.name,
                "receipt": stage_receipt.render(),
                "doc_id": stage_receipt.doc_id,
                "chunks": stage_receipt.chunks,
                "tables": stage_receipt.tables,
                "media": stage_receipt.media,
                "existing": stage_receipt.existing,
            },
        )

    def _raw_fallback(self, dest: Path, raw: bytes) -> dict:
        title = dest.name.replace('"', "'")
        if dest.suffix.lower() == ".csv":
            # CSVs become refinable table_blobs: copy into attachments and
            # assert with attach: provenance so the engine parses the rows
            key = dest.stem
            shutil.copy(dest, self.attach_dir / f"{key}.csv")
            program = (
                f'assert table_blob {{title: "{title}", payload: attach:{key}}} as up'
            )
        else:
            program = f'assert table_blob {{title: "{title}", payload: "file:{dest.name}"}} as up'
        receipt = self.session.run(program)
        return {"stored": dest.name, "receipt": receipt}

    def _handle_extract(self) -> None:
        qs = parse_qs(urlparse(self.path).query)
        doc_id = qs.get("doc", [""])[0]
        agent = qs.get("agent", ["claude"])[0]
        if not doc_id:
            self._json(400, {"error": "doc is required"})
            return
        try:
            runner = get_runner(agent)
        except RunnerError as e:
            self._json(400, {"error": str(e)})
            return
        receipt = extract(self.session, doc_id, runner)
        self._json(
            200,
            {
                "chunks_done": receipt.chunks_done,
                "chunks_failed": receipt.chunks_failed,
                "budget_spent": receipt.budget_spent,
                "stopped_early": receipt.stopped_early,
                "lines": receipt.lines,
            },
        )

    def _handle_playbook(self) -> None:
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        agent = qs.get("agent", ["claude"])[0]
        unhinged = qs.get("unhinged", ["0"])[0] == "1"
        body = self._read_body()
        if not body:
            self._json(400, {"error": "empty playbook"})
            return
        try:
            runner = get_runner(agent)
        except RunnerError as e:
            self._json(400, {"error": str(e)})
            return

        token = uuid.uuid4().hex
        path = self.playbook_dir / f"{token}.md"
        path.write_bytes(body)

        if unhinged:
            try:
                receipt = compile_playbook(self.session, path, runner, unhinged=True)
            except (ParseError, VerifyError, RuntimeError) as e:
                self._json(400, {"error": str(e)})
                return
            self._json(
                200,
                {
                    "doc_id": receipt.doc_id,
                    "applied": receipt.applied,
                    "deprecated": receipt.deprecated,
                    "focus": receipt.focus,
                },
            )
            return

        cap = _CapturingRunner(runner)
        try:
            receipt = compile_playbook(
                self.session, path, cap, unhinged=False, confirm=lambda text: False
            )
        except (ParseError, VerifyError) as e:
            self._json(400, {"error": str(e)})
            return
        blocks = {tag: text.strip() for tag, text in BLOCK_RE.findall(cap.output)}
        pending[token] = cap.output
        self._json(
            200,
            {
                "token": token,
                "proposal": {
                    "doc_id": receipt.doc_id,
                    "program": blocks.get("theorem", ""),
                    "summary": blocks.get("summary", ""),
                    "focus": blocks.get("focus", ""),
                },
            },
        )

    def _handle_playbook_apply(self) -> None:
        body = self._read_body()
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}
        token = payload.get("token", "")
        program_output = pending.pop(token, None)
        if program_output is None:
            self._json(404, {"error": "unknown or expired token"})
            return
        path = self.playbook_dir / f"{token}.md"
        replay = _ReplayRunner(program_output)
        try:
            receipt = compile_playbook(self.session, path, replay, unhinged=True)
        except (ParseError, VerifyError, RuntimeError) as e:
            self._json(400, {"error": str(e)})
            return
        self._json(
            200,
            {
                "doc_id": receipt.doc_id,
                "applied": receipt.applied,
                "deprecated": receipt.deprecated,
                "focus": receipt.focus,
            },
        )

    def log_message(self, fmt: str, *args) -> None:
        pass  # keep the terminal quiet


def make_server(db: str | Path, port: int = 0) -> HTTPServer:
    db = Path(db)
    Handler.session = Session(db, Schema.supply_chain())
    Handler.files_dir = db / "files"
    Handler.attach_dir = db / "attachments"
    Handler.playbook_dir = db / "playbooks"
    Handler.files_dir.mkdir(parents=True, exist_ok=True)
    Handler.attach_dir.mkdir(parents=True, exist_ok=True)
    Handler.playbook_dir.mkdir(parents=True, exist_ok=True)

    # single-threaded on purpose: the engine is single-writer
    return HTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="./demo-db")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    server = make_server(args.db, args.port)
    port = server.server_address[1]
    print(f"theorem upload demo: http://127.0.0.1:{port}  (db: {args.db})")
    server.serve_forever()


if __name__ == "__main__":
    main()

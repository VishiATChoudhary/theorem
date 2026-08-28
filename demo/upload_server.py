"""Minimal upload interface for theorem.

Run:  uv run python demo/upload_server.py  [--db ./demo-db] [--port 8765]

Serves a single-page uploader on http://127.0.0.1:8765. Any file type is
accepted and stored under <db>/files/. CSV uploads are additionally copied
into <db>/attachments/ and asserted as a table_blob node, so they can be
refined into typed graph nodes from the REPL afterwards. Every upload
returns the engine receipt.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from theorem.schema import Schema
from theorem.session import Session

MAX_BYTES = 50 * 1024 * 1024  # 50 MB per file

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
  #drop { border: 2px dashed #7c5cff88; border-radius: 12px; padding: 3rem 1rem;
          text-align: center; cursor: pointer; transition: background .15s; }
  #drop.hover { background: #7c5cff22; }
  #drop input { display: none; }
  ul { list-style: none; padding: 0; }
  li { padding: .6rem .8rem; margin: .4rem 0; border-radius: 8px;
       background: #7c5cff11; font-size: .9rem; }
  li b { font-weight: 600; }
  pre { margin: .4rem 0 0; font-size: .75rem; white-space: pre-wrap;
        opacity: .75; }
  .err { background: #ff5c5c22; }
</style>
</head>
<body>
<h1>theorem<span class="dot">.</span> upload</h1>
<div id="drop">
  drop files here or click to choose
  <input type="file" id="file" multiple>
</div>
<ul id="list"></ul>
<script>
const drop = document.getElementById('drop');
const input = document.getElementById('file');
const list = document.getElementById('list');

drop.addEventListener('click', () => input.click());
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('hover'); });
drop.addEventListener('dragleave', () => drop.classList.remove('hover'));
drop.addEventListener('drop', e => {
  e.preventDefault(); drop.classList.remove('hover');
  upload(e.dataTransfer.files);
});
input.addEventListener('change', () => upload(input.files));

async function upload(files) {
  for (const f of files) {
    const li = document.createElement('li');
    li.innerHTML = `<b>${f.name}</b> … uploading`;
    list.prepend(li);
    try {
      const res = await fetch('/upload?name=' + encodeURIComponent(f.name),
                              { method: 'POST', body: f });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      li.innerHTML = `<b>${f.name}</b> (${(f.size/1024).toFixed(1)} KB) stored`
                   + `<pre>${data.receipt}</pre>`;
    } catch (err) {
      li.classList.add('err');
      li.innerHTML = `<b>${f.name}</b> failed: ${err.message}`;
    }
  }
  refresh();
}

async function refresh() {
  const res = await fetch('/files');
  const data = await res.json();
  document.title = `theorem · upload (${data.files.length})`;
}
refresh();
</script>
</body>
</html>
"""


def sanitize(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name.lstrip(".") or "unnamed"


class Handler(BaseHTTPRequestHandler):
    session: Session
    files_dir: Path
    attach_dir: Path

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        url = urlparse(self.path)
        if url.path != "/upload":
            self._json(404, {"error": "not found"})
            return
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
        remaining = length
        with dest.open("wb") as f:
            while remaining:
                chunk = self.rfile.read(min(remaining, 1 << 16))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)

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
        self._json(200, {"stored": dest.name, "receipt": receipt})

    def log_message(self, fmt: str, *args) -> None:
        pass  # keep the terminal quiet


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="./demo-db")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    db = Path(args.db)
    Handler.session = Session(db, Schema.supply_chain())
    Handler.files_dir = db / "files"
    Handler.attach_dir = db / "attachments"
    Handler.files_dir.mkdir(parents=True, exist_ok=True)
    Handler.attach_dir.mkdir(parents=True, exist_ok=True)

    # single-threaded on purpose: the engine is single-writer
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"theorem upload demo: http://127.0.0.1:{args.port}  (db: {db})")
    server.serve_forever()


if __name__ == "__main__":
    main()

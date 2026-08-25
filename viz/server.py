"""GraphLang tour server: a real Session behind a tiny stdlib HTTP API.

Endpoints:
  GET  /            the single-page app
  POST /run         {"text": "<program>"} -> {"output", "graph", "highlights"}
  POST /reset       fresh session (new database directory)
  GET  /graph       current graph snapshot

Run: uv run python -m viz.server  (then open http://localhost:8848)
"""

from __future__ import annotations

import json
import shutil
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from graphlang.ast_nodes import Return
from graphlang.engine import health
from graphlang.parser import parse
from graphlang.schema import Schema
from graphlang.session import Session
from graphlang.verifier import verify

PORT = 8848
HERE = Path(__file__).parent

SAMPLE_CSV = "item,unit_eur\nanode,2.5\ncathode,3.5\nseparator,1.2\n"


class Tour:
    def __init__(self):
        self.reset()

    def reset(self):
        self.dir = Path(tempfile.mkdtemp(prefix="graphlang-tour-"))
        self.session = Session(self.dir / "db", Schema.supply_chain())
        att = self.session.store.path / "attachments"
        att.mkdir(exist_ok=True)
        (att / "prices.csv").write_text(SAMPLE_CSV)

    def snapshot(self) -> dict:
        store = self.session.store
        schema = self.session.schema
        nodes = []
        for n in store.nodes.values():
            if store.resolve(n.id) != n.id:
                continue  # absorbed by a merge; survivor carries on
            nodes.append({
                "id": n.id,
                "cls": n.cls,
                "name": str(n.props.get("name") or n.props.get("title") or n.id),
                "state": n.state,
                "retired": n.retired_at is not None,
                "origin": n.origin,
                "flags": len(n.flags),
                "health": health.scores(store, n.id),
                "props": {k: v for k, v in n.props.items()
                          if not k.startswith("_")},
            })
        edges = []
        for e in store.edge_index.values():
            if e.retired_at is not None:
                continue
            roles = {r: store.resolve(nid) for r, nid in e.roles.items()}
            ids = list(roles.values())
            if len(set(ids)) < 2:
                continue
            edges.append({"id": e.id, "type": e.type,
                          "source": ids[0], "target": ids[1],
                          "roles": roles})
        dups = []
        seen = set()
        for rec in store.dup_ledger:
            a, b = store.resolve(rec["a"]), store.resolve(rec["b"])
            pair = frozenset((a, b))
            if a == b or pair in store.distinct_pairs or pair in seen:
                continue
            seen.add(pair)
            dups.append({"a": a, "b": b, "score": rec["score"]})
        aliases = [{"absorbed": k, "survivor": store.resolve(k)}
                   for k in store.aliases]
        classes = {name: {"status": c.status, "base": c.base}
                   for name, c in schema.classes.items()}
        return {"nodes": nodes, "edges": edges, "dups": dups,
                "aliases": aliases, "classes": classes,
                "position": store.position}

    def highlights(self, text: str) -> list[str]:
        """Node ids named in a read program's final return, best effort."""
        try:
            stmts = parse(text)
            if any(not type(s).__name__ in
                   ("Find", "Follow", "GroupBy", "Aggregate", "Compute",
                    "Return", "SchemaStmt") for s in stmts):
                return []
            if not any(isinstance(s, Return) for s in stmts):
                return []
            plans = verify(stmts, self.session.schema)
            store = self.session.store
            ids: set[str] = set()
            # walk the pipeline once, collecting every node bound in any column
            from graphlang.engine.executor import Table, _apply_pipeline_stmt
            table = Table()
            for plan in plans:
                if isinstance(plan.stmt, Return):
                    break
                _apply_pipeline_stmt(plan.stmt, table, store,
                                     self.session.schema)
            for row in table.rows:
                for key, value in row.items():
                    if not key.startswith("__") and isinstance(value, str) \
                            and value in store.nodes:
                        ids.add(store.resolve(value))
            return sorted(ids)
        except Exception:
            return []


TOUR = Tour()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/graph":
            self._json(TOUR.snapshot())
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/run":
            text = payload.get("text", "")
            highlights = TOUR.highlights(text)
            output = TOUR.session.run(text)
            self._json({"output": output, "graph": TOUR.snapshot(),
                        "highlights": highlights})
        elif self.path == "/reset":
            old = TOUR.dir
            TOUR.reset()
            shutil.rmtree(old, ignore_errors=True)
            self._json({"output": "session reset. fresh graph.",
                        "graph": TOUR.snapshot(), "highlights": []})
        else:
            self.send_error(404)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"GraphLang tour: http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

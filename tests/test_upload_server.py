import http.client
import json
import threading
from urllib.parse import quote

import pytest

from demo.upload_server import make_server  # main() now exposes make_server(db, port)

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


class StubRunner:
    def __init__(self, out):
        self.out = out

    def run(self, prompt):
        return self.out


@pytest.fixture
def server(tmp_path):
    srv = make_server(tmp_path / "db", port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


def _post(port, path, body=b"", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    return resp.status, data


def test_upload_stages_markdown(server):
    status, data = _post(server, "/upload?name=n.md", body=b"# T\n\nhello world")
    assert status == 200
    assert data["chunks"] >= 1 and data["existing"] is False
    assert "doc_id" in data and "tables" in data and "media" in data


def test_reupload_reports_existing(server):
    for _ in range(2):
        status, data = _post(server, "/upload?name=n.md", body=b"# Same\nbody")
    assert status == 200
    assert data["existing"] is True


def test_upload_binary_falls_back_to_raw_storage(server):
    status, data = _post(server, "/upload?name=n.bin", body=b"\x00\x01\x02binary\xff")
    assert status == 200
    assert "stored" in data and "receipt" in data
    assert "chunks" not in data


def test_upload_csv_stages_as_table(server):
    body = b"name,qty\nwidget,3\ngizmo,7\n"
    status, data = _post(server, "/upload?name=parts.csv", body=body)
    assert status == 200
    assert data["tables"] == 1
    assert data["existing"] is False


def test_files_lists_uploads(server):
    _post(server, "/upload?name=n.md", body=b"# T\n\nhello world")
    conn = http.client.HTTPConnection("127.0.0.1", server)
    conn.request("GET", "/files")
    data = json.loads(conn.getresponse().read())
    conn.close()
    assert "n.md" in data["files"]


def test_extract_runs_against_staged_doc(server, monkeypatch):
    import demo.upload_server as us

    _, uploaded = _post(server, "/upload?name=n.md", body=b"# T\n\nhello world")
    doc_id = uploaded["doc_id"]

    monkeypatch.setattr(us, "get_runner", lambda name: StubRunner("nonsense output"))

    status, data = _post(server, f"/extract?doc={quote(doc_id, safe='')}&agent=claude")
    assert status == 200
    assert "chunks_done" in data
    assert "chunks_failed" in data
    assert "budget_spent" in data
    assert "stopped_early" in data


def test_extract_unknown_agent_returns_json_error(server):
    _, uploaded = _post(server, "/upload?name=n.md", body=b"# T\n\nhello world")
    doc_id = uploaded["doc_id"]

    status, data = _post(
        server, f"/extract?doc={quote(doc_id, safe='')}&agent=nonexistent-cli-name"
    )
    assert status == 400
    assert "error" in data


def test_playbook_guided_proposes_then_applies(server, monkeypatch):
    import demo.upload_server as us

    monkeypatch.setattr(us, "get_runner", lambda name: StubRunner(RESPONSE))

    status, data = _post(
        server,
        "/playbook?agent=claude&unhinged=0",
        body=b"# Competitors\nWe track companies that compete with us.",
    )
    assert status == 200
    assert "token" in data
    assert "competitor" in data["proposal"]["program"]

    token = data["token"]
    status, applied = _post(
        server,
        "/playbook/apply",
        body=json.dumps({"token": token}).encode(),
    )
    assert status == 200
    assert "competitor" in applied["applied"]


def test_playbook_unhinged_applies_immediately(server, monkeypatch):
    import demo.upload_server as us

    monkeypatch.setattr(us, "get_runner", lambda name: StubRunner(RESPONSE))

    status, data = _post(
        server,
        "/playbook?agent=claude&unhinged=1",
        body=b"# Competitors\nWe track companies that compete with us.",
    )
    assert status == 200
    assert "competitor" in data["applied"]

"""Generate tests/fixtures/mini.pdf: a minimal one-page PDF with a proper
xref table so pdfplumber (via pdfminer) can parse it.

The handcrafted PDF bytes in the task brief lack a real xref table, which
pdfminer rejects ("No /Root object!"). This script builds the same content
("Hello theorem" text) with correct byte offsets, computed programmatically
so they can't drift out of sync with the object bodies.

Run once: uv run python tests/fixtures/make_mini_pdf.py
"""

from pathlib import Path

HEADER = b"%PDF-1.4\n"

CONTENT_STREAM = b"BT /F1 18 Tf 20 100 Td (Hello theorem) Tj ET\n"

OBJECTS = [
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n",
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n",
    b"4 0 obj<</Length "
    + str(len(CONTENT_STREAM)).encode()
    + b">>stream\n"
    + CONTENT_STREAM
    + b"endstream endobj\n",
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n",
]


def build() -> bytes:
    offsets = [0]  # object 0 is the free-list head, offset unused
    body = bytearray(HEADER)
    for obj in OBJECTS:
        offsets.append(len(body))
        body.extend(obj)

    xref_offset = len(body)
    xref_lines = [b"xref\n", f"0 {len(OBJECTS) + 1}\n".encode()]
    xref_lines.append(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        xref_lines.append(f"{off:010d} 00000 n \n".encode())

    trailer = (
        f"trailer<</Size {len(OBJECTS) + 1}/Root 1 0 R>>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    ).encode()

    return bytes(body) + b"".join(xref_lines) + trailer


if __name__ == "__main__":
    out = Path(__file__).parent / "mini.pdf"
    out.write_bytes(build())
    print(f"wrote {out}")

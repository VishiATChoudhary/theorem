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

from pathlib import Path

import pytest

pytest.importorskip("pdfplumber")

from theorem.ingest.normalize import IngestError, normalize

MINI_PDF = (Path(__file__).parent / "fixtures" / "mini.pdf").read_bytes()


def test_pdf_text_and_pages():
    env = normalize(MINI_PDF, "mini.pdf")
    assert "Hello theorem" in env.body
    assert env.meta["pages"] == 1
    assert env.anchors and env.anchors[0].page == 1


def test_pdf_corrupt_raises_ingest_error():
    with pytest.raises(IngestError):
        normalize(b"%PDF-corrupt garbage", "x.pdf")

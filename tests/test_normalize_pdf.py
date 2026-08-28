from pathlib import Path

import pytest

pytest.importorskip("pdfplumber")

from theorem.ingest.normalize import normalize

MINI_PDF = (Path(__file__).parent / "fixtures" / "mini.pdf").read_bytes()


def test_pdf_text_and_pages():
    env = normalize(MINI_PDF, "mini.pdf")
    assert "Hello theorem" in env.body
    assert env.meta["pages"] == 1
    assert env.anchors and env.anchors[0].page == 1

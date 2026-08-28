import io
import sys
import zipfile

import pytest

from theorem.ingest.normalize import IngestError, normalize


def test_docx_headings_tables():
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Big Title", level=1)
    d.add_paragraph("Some prose.")
    t = d.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "name", "cost"
    t.rows[1].cells[0].text, t.rows[1].cells[1].text = "bolt", "1.0"
    buf = io.BytesIO()
    d.save(buf)
    env = normalize(buf.getvalue(), "r.docx")
    assert "# Big Title" in env.body and "Some prose." in env.body
    assert env.tables[0].rows == [{"name": "bolt", "cost": "1.0"}]


def test_xlsx_sheets_to_tables():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["region", "amount"])
    ws.append(["EU", 42])
    buf = io.BytesIO()
    wb.save(buf)
    env = normalize(buf.getvalue(), "s.xlsx")
    assert env.tables[0].name == "Sales"
    assert env.tables[0].rows == [{"region": "EU", "amount": "42"}]


def test_pptx_slides_and_notes():
    pptx = pytest.importorskip("pptx")
    p = pptx.Presentation()
    slide = p.slides.add_slide(p.slide_layouts[1])
    slide.shapes.title.text = "Pitch"
    slide.placeholders[1].text = "First bullet"
    buf = io.BytesIO()
    p.save(buf)
    env = normalize(buf.getvalue(), "d.pptx")
    assert "# Slide 1" in env.body and "Pitch" in env.body


def _fake_ooxml_bytes(member: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, "<root/>")
    return buf.getvalue()


def test_docx_corrupt_zip_raises_ingest_error():
    pytest.importorskip("docx")
    with pytest.raises(IngestError, match="cannot parse docx"):
        normalize(_fake_ooxml_bytes("word/document.xml"), "d.docx")


def test_docx_without_extra_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "docx", None)
    with pytest.raises(IngestError, match=r"theorem\[office\]"):
        normalize(_fake_ooxml_bytes("word/document.xml"), "d.docx")


def test_xlsx_without_extra_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    with pytest.raises(IngestError, match=r"theorem\[office\]"):
        normalize(_fake_ooxml_bytes("xl/workbook.xml"), "s.xlsx")


def test_pptx_without_extra_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "pptx", None)
    with pytest.raises(IngestError, match=r"theorem\[office\]"):
        normalize(_fake_ooxml_bytes("ppt/presentation.xml"), "d.pptx")

"""Tests for the OCR fallback in PDFLoader.

An image-only PDF (no native text layer) is generated with PyMuPDF so the
native pypdf extraction returns nothing, forcing the OCR branch. The OCR
engine itself is monkeypatched to return canned text, so these tests are
fast and hermetic — they verify the fallback *routing/config gating*, not
RapidOCR's actual recognition (which is validated separately).
"""
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.exceptions import EmptyDocumentError
from app.rag import ocr_engine
from app.rag.pdf_loader import PDFLoader


@pytest.fixture
def image_only_pdf(tmp_path: Path) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
    pix.clear_with(255)  # blank white image, no text layer
    page.insert_image(fitz.Rect(0, 0, 200, 200), pixmap=pix)
    out = tmp_path / "scanned.pdf"
    doc.save(str(out))
    doc.close()
    return out


def test_scanned_pdf_uses_ocr_when_enabled(image_only_pdf, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ocr_enabled", True)
    monkeypatch.setattr(
        ocr_engine.OCREngine, "image_to_text", lambda self, png_bytes: "recovered text from image"
    )

    pages = PDFLoader().load(image_only_pdf)

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert "recovered text from image" in pages[0].text


def test_scanned_pdf_raises_when_ocr_disabled(image_only_pdf, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ocr_enabled", False)

    with pytest.raises(EmptyDocumentError):
        PDFLoader().load(image_only_pdf)

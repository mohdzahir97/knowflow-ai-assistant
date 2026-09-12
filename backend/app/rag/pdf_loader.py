"""PDF text extraction using pypdf, with an OCR fallback for scanned PDFs.

Native text extraction (pypdf) is tried first for every page. Pages that
yield no text — typical of scanned / image-only PDFs — are optionally sent
through OCR (see app/rag/ocr_engine.py) when `OCR_ENABLED` is set.

Isolated behind `PDFLoader` so a future swap (e.g. to `unstructured` for
richer layout parsing) touches only this file.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import get_settings
from app.core.exceptions import CorruptedFileError, EmptyDocumentError
from app.core.logging import get_logger, log_extra
from app.rag.ocr_engine import get_ocr_engine

logger = get_logger("app.rag.pdf_loader")


@dataclass
class PageContent:
    page_number: int
    text: str


class PDFLoader:
    def load(self, file_path: Path) -> List[PageContent]:
        try:
            reader = PdfReader(str(file_path))
        except (PdfReadError, OSError, ValueError) as exc:
            logger.warning("Failed to open PDF", extra=log_extra(file=file_path.name, error=str(exc)))
            raise CorruptedFileError(f"'{file_path.name}' could not be read. It may be corrupted.") from exc

        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise CorruptedFileError(f"'{file_path.name}' is password-protected and cannot be processed.") from exc

        pages: List[PageContent] = []
        pages_needing_ocr: List[int] = []

        for index, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception as exc:
                logger.warning(
                    "Failed to extract text from page",
                    extra=log_extra(file=file_path.name, page=index, error=str(exc)),
                )
                text = ""
            if text:
                pages.append(PageContent(page_number=index, text=text))
            else:
                pages_needing_ocr.append(index)

        settings = get_settings()
        if pages_needing_ocr and settings.ocr_enabled:
            logger.info(
                "Running OCR fallback on pages with no native text",
                extra=log_extra(file=file_path.name, ocr_page_count=len(pages_needing_ocr)),
            )
            pages.extend(self._ocr_pages(file_path, pages_needing_ocr, settings.ocr_dpi))
            pages.sort(key=lambda p: p.page_number)

        if not pages:
            raise EmptyDocumentError(
                f"'{file_path.name}' contains no extractable text. If this is a scanned document, "
                "ensure OCR is enabled on the server."
            )

        logger.info("PDF text extracted", extra=log_extra(file=file_path.name, page_count=len(pages)))
        return pages

    def _ocr_pages(self, file_path: Path, page_numbers: List[int], dpi: int) -> List[PageContent]:
        """Render the given (1-indexed) pages to images and OCR them.

        A failure on any single page is logged and skipped rather than
        aborting the whole document.
        """
        import fitz  # PyMuPDF — imported lazily so non-OCR paths pay nothing.

        ocr = get_ocr_engine()
        results: List[PageContent] = []
        try:
            doc = fitz.open(str(file_path))
        except Exception as exc:
            logger.warning("OCR could not open PDF for rendering", extra=log_extra(file=file_path.name, error=str(exc)))
            return results

        try:
            for page_number in page_numbers:
                try:
                    pixmap = doc[page_number - 1].get_pixmap(dpi=dpi)
                    text = ocr.image_to_text(pixmap.tobytes("png"))
                except Exception as exc:
                    logger.warning(
                        "OCR failed for page",
                        extra=log_extra(file=file_path.name, page=page_number, error=str(exc)),
                    )
                    continue
                if text:
                    results.append(PageContent(page_number=page_number, text=text))
        finally:
            doc.close()

        return results

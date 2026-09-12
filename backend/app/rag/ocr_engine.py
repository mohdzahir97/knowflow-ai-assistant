"""Optional OCR fallback for scanned / image-only PDFs.

Uses RapidOCR (ONNX runtime) rather than Tesseract so that no system
binary needs to be installed — it works identically on Windows and inside
the Docker image, and reuses the `onnxruntime` dependency that ChromaDB
already pulls in.

The engine is loaded lazily and cached process-wide: model initialization
is expensive and should happen at most once. `lru_cache` guarantees the
initialization is thread-safe, and onnxruntime inference is safe to call
concurrently from the request threadpool.
"""
from functools import lru_cache

from app.core.exceptions import CorruptedFileError
from app.core.logging import get_logger

logger = get_logger("app.rag.ocr")


@lru_cache(maxsize=1)
def _get_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:  # pragma: no cover - defensive; dependency is pinned
        raise CorruptedFileError(
            "OCR support is not available on the server (rapidocr-onnxruntime is not installed)."
        ) from exc
    logger.info("Initializing OCR engine")
    return RapidOCR()


class OCREngine:
    def image_to_text(self, png_bytes: bytes) -> str:
        engine = _get_engine()
        result, _ = engine(png_bytes)
        if not result:
            return ""
        return "\n".join(line[1] for line in result).strip()


def get_ocr_engine() -> OCREngine:
    return OCREngine()

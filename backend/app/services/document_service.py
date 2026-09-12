"""Document upload/list/delete/clear — the ingestion half of the RAG pipeline.

Wires PDFLoader -> DocumentChunker -> EmbeddingProviderFactory ->
VectorStoreService, and keeps the SQL `Document` table as the per-user
system of record so listing/deleting never needs to touch ChromaDB.
"""
from pathlib import Path
from typing import List, Set, Tuple

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    AppError,
    FileTooLargeError,
    ResourceNotFoundError,
    UnsupportedFileTypeError,
    VectorStoreError,
)
from app.core.logging import get_logger, log_extra
from app.db.base import generate_uuid
from app.db.models.document import Document, DocumentStatus
from app.db.models.user import User
from app.providers.embeddings import EmbeddingProviderFactory
from app.rag.chunker import DocumentChunker
from app.rag.keyword_index import get_keyword_index
from app.rag.pdf_loader import PDFLoader
from app.services.vector_store_service import VectorStoreService

logger = get_logger("app.documents")

_ALLOWED_CONTENT_TYPES = {"application/pdf"}
_ALLOWED_EXTENSIONS = {".pdf"}


def _safe_filename(filename: str) -> str:
    """Strip any path components to prevent path traversal via a crafted filename."""
    return Path(filename).name


class DocumentService:
    def __init__(self) -> None:
        self._pdf_loader = PDFLoader()
        self._chunker = DocumentChunker()
        self._vector_store = VectorStoreService()

    def _validate_upload(self, file: UploadFile, content: bytes) -> None:
        settings = get_settings()
        extension = Path(file.filename or "").suffix.lower()
        if file.content_type not in _ALLOWED_CONTENT_TYPES or extension not in _ALLOWED_EXTENSIONS:
            raise UnsupportedFileTypeError(
                f"'{file.filename}' is not a supported file type. Only PDF files are accepted."
            )
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            raise FileTooLargeError(
                f"'{file.filename}' exceeds the maximum allowed size of {settings.max_upload_size_mb}MB."
            )
        if len(content) == 0:
            raise UnsupportedFileTypeError(f"'{file.filename}' is empty.")

    def upload(
        self,
        db: Session,
        user: User,
        file: UploadFile,
        embedding_provider: str,
        embedding_model: str,
    ) -> Document:
        """Process and index a single PDF, atomically from the caller's point of view.

        No `Document` row is created — and no partial/failed record is ever
        left behind — unless PDF parsing, chunking, and embedding all
        succeed. On any failure the temp file is removed and any vectors
        that may have been partially written are cleaned up on a
        best-effort basis before the error propagates.
        """
        content = file.file.read()
        self._validate_upload(file, content)

        # Fail fast if the embedding provider/model is invalid or unconfigured,
        # before writing anything to disk or the database.
        embeddings = EmbeddingProviderFactory.create_embeddings(embedding_provider, embedding_model)

        settings = get_settings()
        document_id = generate_uuid()
        safe_filename = _safe_filename(file.filename or "document.pdf")
        user_upload_dir = settings.upload_path / user.id
        user_upload_dir.mkdir(parents=True, exist_ok=True)
        stored_path = user_upload_dir / f"{document_id}_{safe_filename}"
        stored_path.write_bytes(content)
        logger.info("Document processing started", extra=log_extra(user_id=user.id, document_id=document_id, filename=safe_filename))

        try:
            pages = self._pdf_loader.load(stored_path)
            chunks = self._chunker.chunk_pages(pages, filename=safe_filename, document_id=document_id, user_id=user.id)
            self._vector_store.insert_documents(embedding_provider, embedding_model, embeddings, chunks)
            get_keyword_index().invalidate()
        except AppError as exc:
            self._rollback_failed_upload(stored_path, embedding_provider, embedding_model, document_id)
            logger.warning(
                "Document processing failed; no record was saved",
                extra=log_extra(user_id=user.id, document_id=document_id, error=exc.message),
            )
            raise
        except Exception as exc:
            self._rollback_failed_upload(stored_path, embedding_provider, embedding_model, document_id)
            logger.exception(
                "Unexpected error while processing document; no record was saved",
                extra=log_extra(user_id=user.id, document_id=document_id),
            )
            raise VectorStoreError(f"Failed to index '{safe_filename}': {exc}") from exc

        # Only reachable on full success — this is the single point where a
        # Document row is ever created.
        document = Document(
            id=document_id,
            user_id=user.id,
            filename=safe_filename,
            stored_path=str(stored_path),
            content_type=file.content_type or "application/pdf",
            file_size_bytes=len(content),
            status=DocumentStatus.INDEXED,
            page_count=len(pages),
            chunk_count=len(chunks),
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        logger.info(
            "Document indexed",
            extra=log_extra(user_id=user.id, document_id=document_id, page_count=document.page_count, chunk_count=document.chunk_count),
        )
        return document

    def _rollback_failed_upload(
        self, stored_path: Path, embedding_provider: str, embedding_model: str, document_id: str
    ) -> None:
        stored_path.unlink(missing_ok=True)
        try:
            self._vector_store.delete_document(embedding_provider, embedding_model, document_id)
            get_keyword_index().invalidate()
        except Exception:
            # Best-effort: nothing was necessarily inserted, so a failure
            # here must never mask the original processing error.
            pass

    # The methods below operate on the shared knowledge base, so they are not
    # filtered by uploader. `Document.user_id` records *who* uploaded a
    # document for audit purposes; it is deliberately not an access boundary.
    # Access is controlled at the route layer, which admits admins only.

    def list_documents(self, db: Session) -> List[Document]:
        """Every document in the knowledge base, newest first."""
        return list(db.scalars(select(Document).order_by(Document.created_at.desc())))

    def get_document(self, db: Session, document_id: str) -> Document:
        document = db.get(Document, document_id)
        if not document:
            raise ResourceNotFoundError("Document not found.")
        return document

    def delete_document(self, db: Session, document_id: str) -> None:
        document = self.get_document(db, document_id)
        self._vector_store.delete_document(document.embedding_provider, document.embedding_model, document_id)
        get_keyword_index().invalidate()
        Path(document.stored_path).unlink(missing_ok=True)
        db.delete(document)
        db.commit()
        logger.info("Document deleted", extra=log_extra(document_id=document_id))

    def clear_all(self, db: Session) -> None:
        """Wipe the entire knowledge base. Affects every user's answers."""
        documents = self.list_documents(db)
        embedding_configs: Set[Tuple[str, str]] = {
            (d.embedding_provider, d.embedding_model) for d in documents if d.embedding_provider and d.embedding_model
        }
        for provider, model in embedding_configs:
            self._vector_store.clear_collection(provider, model)
        get_keyword_index().invalidate()
        for document in documents:
            Path(document.stored_path).unlink(missing_ok=True)
            db.delete(document)
        db.commit()
        logger.warning("Knowledge base cleared", extra=log_extra(document_count=len(documents)))


def get_document_service() -> DocumentService:
    return DocumentService()

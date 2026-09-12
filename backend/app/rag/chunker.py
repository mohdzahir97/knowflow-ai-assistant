"""Splits extracted PDF pages into embeddable chunks with citation metadata."""
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings
from app.core.logging import get_logger, log_extra
from app.rag.pdf_loader import PageContent

logger = get_logger("app.rag.chunker")


class DocumentChunker:
    def __init__(self) -> None:
        settings = get_settings()
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            length_function=len,
        )

    def chunk_pages(self, pages: List[PageContent], filename: str, document_id: str, user_id: str) -> List[Document]:
        chunks: List[Document] = []
        for page in pages:
            for chunk_index, chunk_text in enumerate(self._splitter.split_text(page.text)):
                chunk_id = f"{document_id}_p{page.page_number}_c{chunk_index}"
                chunks.append(
                    Document(
                        page_content=chunk_text,
                        metadata={
                            "chunk_id": chunk_id,
                            "document_id": document_id,
                            "user_id": user_id,
                            "filename": filename,
                            "source": filename,
                            "page": page.page_number,
                        },
                    )
                )

        logger.info(
            "Document chunked",
            extra=log_extra(document_id=document_id, filename=filename, chunk_count=len(chunks)),
        )
        return chunks

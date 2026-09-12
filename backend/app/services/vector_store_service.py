"""ChromaDB-backed persistent vector store for the shared knowledge base.

The knowledge base is a single corpus curated by admins and queried by every
end user, so collections are keyed by `(embedding_provider, embedding_model)`
alone. The embedding config still has to be part of the key because Chroma
requires uniform vector dimensionality within a collection, so documents
indexed with different embedding models cannot be mixed.

Note on isolation: an earlier design keyed collections by user, which made
per-user document isolation structural. That property intentionally no
longer applies to documents - they are shared by design. Isolation now
applies to *conversations*: chats, projects and messages are owned by a
user and access is enforced in the service layer. Do not reintroduce
user-scoped collections without revisiting that decision.

Administrative operations (list/delete/clear) are metadata/ID-based and
never call the embedding function, so they work with an inert placeholder
embeddings object - removing a document should never require a live,
correctly configured provider API key.
"""
import hashlib
from typing import List, Optional, Tuple

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.core.config import get_settings
from app.core.exceptions import VectorStoreError
from app.core.logging import get_logger, log_extra

logger = get_logger("app.rag.vector_store")


class _InertEmbeddings(Embeddings):
    """Placeholder used for operations that never embed text (delete/list/clear)."""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError("This operation does not require embedding computation.")

    def embed_query(self, text: str) -> List[float]:
        raise NotImplementedError("This operation does not require embedding computation.")


class VectorStoreService:
    def collection_name(self, embedding_provider: str, embedding_model: str) -> str:
        """Name of the shared collection for one embedding configuration.

        Public because the migration tooling needs to address collections by
        name without duplicating the hashing rule.
        """
        digest = hashlib.sha1(f"{embedding_provider}:{embedding_model}".encode("utf-8")).hexdigest()
        return f"kb_shared_{digest}"

    def _get_store(
        self,
        embedding_provider: str,
        embedding_model: str,
        embeddings: Optional[Embeddings] = None,
    ) -> Chroma:
        settings = get_settings()
        return Chroma(
            collection_name=self.collection_name(embedding_provider, embedding_model),
            embedding_function=embeddings or _InertEmbeddings(),
            persist_directory=str(settings.chroma_path),
        )

    def insert_documents(
        self,
        embedding_provider: str,
        embedding_model: str,
        embeddings: Embeddings,
        documents: List[Document],
    ) -> List[str]:
        if not documents:
            return []
        store = self._get_store(embedding_provider, embedding_model, embeddings)
        try:
            ids = store.add_documents(documents)
        except Exception as exc:
            logger.error("Vector insertion failed", extra=log_extra(error=str(exc)))
            raise VectorStoreError(f"Failed to store document embeddings: {exc}") from exc
        logger.info("Vectors inserted", extra=log_extra(chunk_count=len(ids)))
        return ids

    def similarity_search(
        self,
        embedding_provider: str,
        embedding_model: str,
        embeddings: Embeddings,
        query: str,
        top_k: int,
        document_ids: Optional[List[str]] = None,
    ) -> List[Document]:
        store = self._get_store(embedding_provider, embedding_model, embeddings)
        search_filter = {"document_id": {"$in": document_ids}} if document_ids else None
        try:
            results = store.similarity_search(query, k=top_k, filter=search_filter)
        except Exception as exc:
            logger.error("Vector search failed", extra=log_extra(error=str(exc)))
            raise VectorStoreError(f"Similarity search failed: {exc}") from exc
        logger.info("Vector search completed", extra=log_extra(top_k=top_k, retrieved_count=len(results)))
        return results

    async def asimilarity_search(
        self,
        embedding_provider: str,
        embedding_model: str,
        embeddings: Embeddings,
        query: str,
        top_k: int,
        document_ids: Optional[List[str]] = None,
    ) -> List[Document]:
        """Async counterpart of `similarity_search`.

        Chroma's async methods delegate to a threadpool internally, but the
        embedding call inside them is real network I/O for hosted providers,
        so awaiting still yields the event loop rather than pinning a worker
        for the round trip.
        """
        store = self._get_store(embedding_provider, embedding_model, embeddings)
        search_filter = {"document_id": {"$in": document_ids}} if document_ids else None
        try:
            results = await store.asimilarity_search(query, k=top_k, filter=search_filter)
        except Exception as exc:
            logger.error("Vector search failed", extra=log_extra(error=str(exc)))
            raise VectorStoreError(f"Similarity search failed: {exc}") from exc
        logger.info("Vector search completed", extra=log_extra(top_k=top_k, retrieved_count=len(results)))
        return results

    async def asimilarity_search_with_scores(
        self,
        embedding_provider: str,
        embedding_model: str,
        embeddings: Embeddings,
        query: str,
        top_k: int,
        document_ids: Optional[List[str]] = None,
    ) -> List[Tuple[Document, float]]:
        """Retrieve chunks together with normalised 0-1 relevance scores.

        Corrective RAG needs a measure of how good the retrieved context is.
        Chroma returns relevance scores alongside results at no extra cost,
        which means context quality can be judged without spending an LLM
        call on a grader.
        """
        store = self._get_store(embedding_provider, embedding_model, embeddings)
        search_filter = {"document_id": {"$in": document_ids}} if document_ids else None
        try:
            results = await store.asimilarity_search_with_relevance_scores(
                query, k=top_k, filter=search_filter
            )
        except Exception as exc:
            logger.error("Scored vector search failed", extra=log_extra(error=str(exc)))
            raise VectorStoreError(f"Similarity search failed: {exc}") from exc

        # Chroma derives relevance from a distance metric and can emit values
        # outside 0-1 when embeddings are not unit-normalised. Context grading
        # is calibrated on a 0-1 scale, so an out-of-range score would make
        # every result grade "poor" and trigger pointless corrective
        # retrieval. Clamp, and say so loudly rather than silently.
        clamped: List[Tuple[Document, float]] = []
        out_of_range = 0
        for document, score in results:
            if score < 0.0 or score > 1.0:
                out_of_range += 1
                score = min(1.0, max(0.0, score))
            clamped.append((document, score))

        if out_of_range:
            logger.warning(
                "Relevance scores outside 0-1 were clamped; grading thresholds "
                "assume normalised scores, so check the embedding model",
                extra=log_extra(out_of_range=out_of_range, embedding_model=embedding_model),
            )

        logger.info(
            "Scored vector search completed",
            extra=log_extra(
                top_k=top_k,
                retrieved_count=len(clamped),
                best_score=round(clamped[0][1], 4) if clamped else None,
            ),
        )
        return clamped

    def get_all_chunks(self, embedding_provider: str, embedding_model: str) -> List[Document]:
        """Every chunk in a collection, for building the keyword index.

        Reads text and metadata only - no embeddings - so this stays cheap
        relative to the vectors themselves. Callers should cache the result;
        it is not intended to run per query.
        """
        store = self._get_store(embedding_provider, embedding_model)
        try:
            record = store.get(include=["documents", "metadatas"])
        except Exception as exc:
            raise VectorStoreError(f"Failed to read collection contents: {exc}") from exc

        texts = record.get("documents") or []
        metadatas = record.get("metadatas") or []
        return [
            Document(page_content=text or "", metadata=metadata or {})
            for text, metadata in zip(texts, metadatas)
        ]

    def list_indexed_document_ids(self, embedding_provider: str, embedding_model: str) -> List[str]:
        store = self._get_store(embedding_provider, embedding_model)
        try:
            record = store.get(include=["metadatas"])
        except Exception as exc:
            raise VectorStoreError(f"Failed to list indexed documents: {exc}") from exc
        document_ids = {meta.get("document_id") for meta in record.get("metadatas", []) if meta}
        return sorted(doc_id for doc_id in document_ids if doc_id)

    def delete_document(self, embedding_provider: str, embedding_model: str, document_id: str) -> None:
        store = self._get_store(embedding_provider, embedding_model)
        try:
            store.delete(where={"document_id": document_id})
        except Exception as exc:
            logger.error("Vector deletion failed", extra=log_extra(document_id=document_id, error=str(exc)))
            raise VectorStoreError(f"Failed to delete document vectors: {exc}") from exc
        logger.info("Vectors deleted", extra=log_extra(document_id=document_id))

    def clear_collection(self, embedding_provider: str, embedding_model: str) -> None:
        """Drop an entire embedding-configuration collection.

        This wipes shared knowledge for every user, so callers must confirm
        the request came from an admin.
        """
        store = self._get_store(embedding_provider, embedding_model)
        try:
            store.delete_collection()
        except Exception as exc:
            logger.error("Vector store clear failed", extra=log_extra(error=str(exc)))
            raise VectorStoreError(f"Failed to clear the vector store: {exc}") from exc
        logger.info(
            "Knowledge base collection cleared",
            extra=log_extra(embedding_provider=embedding_provider, embedding_model=embedding_model),
        )


def get_vector_store_service() -> VectorStoreService:
    return VectorStoreService()

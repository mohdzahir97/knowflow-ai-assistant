"""Thin retrieval layer sitting between the chat service and the vector store.

Kept as its own seam so future upgrades (hybrid search, reranking,
Corrective RAG's relevance grading, Graph RAG traversal) can be inserted
here without touching `ChatService` or the vector store itself.
"""
import asyncio
from typing import List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.core.config import get_settings
from app.core.logging import get_logger, log_extra
from app.core.tracing import traced
from app.rag.keyword_index import get_keyword_index
from app.services.vector_store_service import VectorStoreService

logger = get_logger("app.rag.retriever")


class Retriever:
    def __init__(self, vector_store_service: VectorStoreService) -> None:
        self._vector_store_service = vector_store_service

    def retrieve(
        self,
        embedding_provider: str,
        embedding_model: str,
        embeddings: Embeddings,
        query: str,
        top_k: Optional[int] = None,
        document_ids: Optional[List[str]] = None,
    ) -> List[Document]:
        resolved_top_k = top_k or get_settings().retrieval_top_k
        return self._vector_store_service.similarity_search(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embeddings=embeddings,
            query=query,
            top_k=resolved_top_k,
            document_ids=document_ids,
        )

    @traced("rag.retrieve_scored", run_type="retriever")
    async def aretrieve_scored(
        self,
        embedding_provider: str,
        embedding_model: str,
        embeddings: Embeddings,
        query: str,
        top_k: Optional[int] = None,
        document_ids: Optional[List[str]] = None,
    ) -> Tuple[List[Document], List[float]]:
        """Retrieve with relevance scores, dropping duplicate chunk content.

        Deduplication matters more than it sounds: the same document uploaded
        twice produces byte-identical chunks that retrieve with identical
        scores, so without this a top-k of 4 can spend half its slots on
        repeats and silently halve the context the model actually sees.

        Over-fetches to compensate, so removing duplicates does not leave
        fewer results than the caller asked for.
        """
        resolved_top_k = top_k or get_settings().retrieval_top_k
        scored = await self._vector_store_service.asimilarity_search_with_scores(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embeddings=embeddings,
            query=query,
            top_k=resolved_top_k * 2,
            document_ids=document_ids,
        )

        documents: List[Document] = []
        scores: List[float] = []
        seen_content: set[str] = set()
        duplicates = 0

        for document, score in scored:
            fingerprint = document.page_content.strip()
            if fingerprint in seen_content:
                duplicates += 1
                continue
            seen_content.add(fingerprint)
            documents.append(document)
            scores.append(score)
            if len(documents) >= resolved_top_k:
                break

        if duplicates:
            logger.info(
                "Dropped duplicate chunks during retrieval",
                extra=log_extra(duplicate_count=duplicates, returned=len(documents)),
            )
        return documents, scores

    @traced("rag.retrieve_hybrid", run_type="retriever")
    async def aretrieve_hybrid(
        self,
        embedding_provider: str,
        embedding_model: str,
        embeddings: Embeddings,
        query: str,
        top_k: Optional[int] = None,
        document_ids: Optional[List[str]] = None,
    ) -> Tuple[List[Document], List[float], dict]:
        """Fuse vector similarity with BM25 keyword matching.

        Returns `(documents, vector_scores, diagnostics)`.

        `vector_scores` are cosine relevance values, index-aligned with the
        returned documents and 0.0 for chunks only keyword search found.
        They are deliberately *not* the fusion scores: context grading is
        calibrated against the cosine scale, and swapping in a fused score
        would silently invalidate that threshold.

        Ordering comes from Reciprocal Rank Fusion, which combines the two
        result lists by rank rather than by score. That matters because BM25
        scores are unbounded and cosine scores are 0-1, so they cannot be
        compared or averaged directly.
        """
        settings = get_settings()
        resolved_top_k = top_k or settings.retrieval_top_k

        vector_results = await self._vector_store_service.asimilarity_search_with_scores(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embeddings=embeddings,
            query=query,
            top_k=resolved_top_k * 2,
            document_ids=document_ids,
        )

        keyword_results: List[Tuple[Document, float]] = []
        if settings.hybrid_search_enabled:
            try:
                keyword_results = await asyncio.to_thread(
                    self._keyword_search,
                    embedding_provider,
                    embedding_model,
                    query,
                    resolved_top_k * 2,
                    document_ids,
                )
            except Exception as exc:
                # Keyword search is an enhancement; if it fails the request
                # should still be answered from vector results alone.
                logger.warning("Keyword search failed; using vector results only", extra=log_extra(error=str(exc)))

        return self._fuse(vector_results, keyword_results, resolved_top_k, settings.hybrid_rrf_k)

    def _keyword_search(
        self,
        embedding_provider: str,
        embedding_model: str,
        query: str,
        top_k: int,
        document_ids: Optional[List[str]],
    ) -> List[Tuple[Document, float]]:
        """BM25 lookup. Synchronous and CPU-bound, so callers run it off the loop."""
        collection = self._vector_store_service.collection_name(embedding_provider, embedding_model)
        chunks = self._vector_store_service.get_all_chunks(embedding_provider, embedding_model)
        if document_ids:
            allowed = set(document_ids)
            chunks = [c for c in chunks if c.metadata.get("document_id") in allowed]
        return get_keyword_index().search(collection, chunks, query, top_k)

    @staticmethod
    def _fuse(
        vector_results: List[Tuple[Document, float]],
        keyword_results: List[Tuple[Document, float]],
        top_k: int,
        rrf_k: int,
    ) -> Tuple[List[Document], List[float], dict]:
        """Reciprocal Rank Fusion over the two result lists, de-duplicated.

        Identity is the chunk *text*, not the chunk id. That is deliberate:
        uploading the same document twice produces byte-identical chunks
        under different ids, so keying on id would let both copies through
        and waste half of top_k on a repeat. Keying on content collapses
        them, and also merges a chunk found by both retrievers so its ranks
        add rather than competing.
        """
        fused: dict = {}

        def add(results: List[Tuple[Document, float]], source: str) -> None:
            for rank, (document, score) in enumerate(results):
                key = document.page_content.strip()
                entry = fused.setdefault(
                    key,
                    {"document": document, "rrf": 0.0, "vector_score": 0.0, "sources": set()},
                )
                entry["rrf"] += 1.0 / (rrf_k + rank + 1)
                entry["sources"].add(source)
                if source == "vector":
                    entry["vector_score"] = score

        add(vector_results, "vector")
        add(keyword_results, "keyword")

        ordered = sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)[:top_k]

        documents = [entry["document"] for entry in ordered]
        vector_scores = [entry["vector_score"] for entry in ordered]
        diagnostics = {
            "vector_hits": len(vector_results),
            "keyword_hits": len(keyword_results),
            "keyword_only_chunks": sum(1 for e in ordered if e["sources"] == {"keyword"}),
            "fused_returned": len(documents),
        }
        return documents, vector_scores, diagnostics

    @traced("rag.retrieve", run_type="retriever")
    async def aretrieve(
        self,
        embedding_provider: str,
        embedding_model: str,
        embeddings: Embeddings,
        query: str,
        top_k: Optional[int] = None,
        document_ids: Optional[List[str]] = None,
    ) -> List[Document]:
        """Async retrieval. Embedding the query is a network call for every
        hosted provider, so awaiting it keeps the event loop free."""
        resolved_top_k = top_k or get_settings().retrieval_top_k
        return await self._vector_store_service.asimilarity_search(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embeddings=embeddings,
            query=query,
            top_k=resolved_top_k,
            document_ids=document_ids,
        )


def get_retriever() -> Retriever:
    return Retriever(VectorStoreService())

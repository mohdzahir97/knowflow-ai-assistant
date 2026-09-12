"""Retrieval step: turn a search query into scored candidate context."""
from __future__ import annotations

from typing import Optional

from app.core.logging import get_logger, log_extra
from app.rag.pipeline.base import PipelineStep
from app.rag.pipeline.context import RagContext
from app.rag.retriever import Retriever, get_retriever

logger = get_logger("app.rag.pipeline.retrieve")


class RetrieveStep(PipelineStep):
    """Vector similarity search over the shared knowledge base.

    Reads `context.search_query` rather than `context.question` so that the
    corrective loop can re-run this step with a rewritten query while the
    user's original wording stays intact for citations and logging.

    Returns relevance scores alongside the chunks; the grading step needs
    them, and getting them here costs nothing extra.
    """

    name = "retrieve"

    def __init__(self, retriever: Optional[Retriever] = None) -> None:
        self._retriever = retriever or get_retriever()

    async def run(self, context: RagContext) -> None:
        chunks, scores, diagnostics = await self._retriever.aretrieve_hybrid(
            embedding_provider=context.embedding_provider,
            embedding_model=context.embedding_model,
            embeddings=context.embeddings,
            query=context.search_query,
            top_k=context.top_k,
            document_ids=context.document_ids,
        )
        context.chunks = chunks
        context.chunk_scores = scores
        context.attempted_queries.append(context.search_query)
        context.metadata["retrieved_count"] = len(chunks)
        context.metadata.update(diagnostics)
        # Results arrive in fused rank order; re-sorting by cosine score
        # afterwards would discard the keyword signal entirely.
        context.metadata["hybrid_ranked"] = True

        logger.info(
            "Retrieval step completed",
            extra=log_extra(
                user_id=context.user_id,
                retrieved_count=len(chunks),
                best_score=round(max(scores), 4) if scores else None,
                **diagnostics,
            ),
        )

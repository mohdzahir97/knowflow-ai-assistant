"""Retrieval evaluation: is the retrieved context good enough to answer from?

This is the decision Corrective RAG is built around. Classic CRAG spends an
LLM call on a relevance grader; here the judgement is made from the
relevance scores the vector store already returns, so it is effectively
free and adds no latency.

Measured on this corpus with nomic-embed-text: an on-topic query scores
~0.34 and an off-topic one ~0.10. The default threshold of 0.25 sits between
them. Score scales differ by embedding model, so the threshold is
configurable rather than hard-coded.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger, log_extra
from app.rag.pipeline.base import PipelineStep
from app.rag.pipeline.context import RagContext

logger = get_logger("app.rag.pipeline.grade")

VERDICT_GOOD = "good"
VERDICT_POOR = "poor"


class GradeContextStep(PipelineStep):
    """Score the retrieved context and record a good/poor verdict.

    Deliberately does not halt on a poor verdict: the corrective step that
    follows is what decides whether a retry is worthwhile. Grading only
    reports.
    """

    name = "grade_context"

    async def run(self, context: RagContext) -> None:
        settings = get_settings()

        if not context.chunks:
            context.context_verdict = VERDICT_POOR
            context.context_quality = 0.0
            context.metadata["relevant_chunk_count"] = 0
            logger.info("Context graded: nothing retrieved", extra=log_extra(user_id=context.user_id))
            return

        threshold = settings.crag_relevance_threshold
        relevant = [score for score in context.chunk_scores if score >= threshold]
        best = max(context.chunk_scores) if context.chunk_scores else 0.0

        context.context_quality = round(best, 4)
        context.metadata["relevant_chunk_count"] = len(relevant)
        context.metadata["relevance_threshold"] = threshold
        context.context_verdict = (
            VERDICT_GOOD if len(relevant) >= settings.crag_min_relevant_chunks else VERDICT_POOR
        )

        logger.info(
            "Context graded",
            extra=log_extra(
                user_id=context.user_id,
                verdict=context.context_verdict,
                best_score=context.context_quality,
                relevant_chunks=len(relevant),
                threshold=threshold,
            ),
        )

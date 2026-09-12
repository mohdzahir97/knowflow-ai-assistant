"""Corrective retrieval: rewrite the query and try again when context is poor.

The defining behaviour of Corrective RAG. Rather than passing weak context
to the model and hoping, a poor grade triggers a rewrite of the search query
and a second retrieval; the better of the two attempts is kept.

Cost is paid only when it is needed: the rewrite is one LLM call that
happens solely on a poor verdict, so well-matched questions are unaffected.
The loop is bounded by configuration so a hopeless query cannot spin.
"""
from __future__ import annotations



from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import get_settings
from app.core.logging import get_logger, log_extra
from app.providers.llm import LLMProviderFactory
from app.rag.pipeline.base import PipelineStep
from app.rag.pipeline.context import RagContext
from app.rag.pipeline.steps.grade import VERDICT_POOR, GradeContextStep
from app.rag.retriever import Retriever, get_retriever

logger = get_logger("app.rag.pipeline.correct")

_REWRITE_SYSTEM_PROMPT = """You rewrite search queries for a document retrieval system.

The user's question did not match the indexed documents well. Rewrite it as a \
search query more likely to match the wording of formal written documents such \
as policy manuals, handbooks and technical guides.

Rules:
- Keep the original meaning. Do not answer the question.
- Prefer formal terminology likely to appear as headings or section titles.
- Drop conversational filler ("can you tell me", "I want to know").
- Expand obvious abbreviations.
- Reply with the rewritten query only - no preamble, quotes or explanation."""


class CorrectiveRetrievalStep(PipelineStep):
    """Retry retrieval with a rewritten query while the context grades poor."""

    name = "corrective_retrieval"

    def __init__(self, retriever: Retriever | None = None) -> None:
        self._retriever = retriever or get_retriever()
        self._grader = GradeContextStep()

    async def run(self, context: RagContext) -> None:
        settings = get_settings()

        if not settings.crag_enabled or context.context_verdict != VERDICT_POOR:
            return

        max_attempts = settings.crag_max_correction_attempts
        if max_attempts <= 0:
            return

        # Remember the first attempt so a rewrite that retrieves *worse*
        # context can be discarded rather than blindly accepted.
        #
        # Derived from the scores rather than read from context.context_quality
        # so this holds even if grading has not populated that field: seeding
        # from a missing value would start "best" at zero, and then any
        # retry - however bad - would beat it.
        best_chunks = list(context.chunks)
        best_scores = list(context.chunk_scores)
        best_quality = max(context.chunk_scores) if context.chunk_scores else 0.0

        while context.correction_attempts < max_attempts and context.context_verdict == VERDICT_POOR:
            rewritten = await self._rewrite_query(context)
            if not rewritten or rewritten in context.attempted_queries:
                # Count only corrections that actually re-ran retrieval, so
                # `correction_attempts` means "retries performed" rather than
                # "retries considered" - otherwise diagnostics report a
                # correction with no rewritten query to show for it.
                context.metadata["correction_aborted"] = (
                    "empty_rewrite" if not rewritten else "duplicate_rewrite"
                )
                logger.info(
                    "Corrective retrieval stopped: no new usable rewrite",
                    extra=log_extra(user_id=context.user_id, reason=context.metadata["correction_aborted"]),
                )
                break

            context.correction_attempts += 1
            context.search_query = rewritten
            chunks, scores = await self._retriever.aretrieve_scored(
                embedding_provider=context.embedding_provider,
                embedding_model=context.embedding_model,
                embeddings=context.embeddings,
                query=rewritten,
                top_k=context.top_k,
                document_ids=context.document_ids,
            )
            context.chunks = chunks
            context.chunk_scores = scores
            context.attempted_queries.append(rewritten)

            await self._grader.run(context)

            quality = context.context_quality or 0.0
            if quality > best_quality:
                best_chunks, best_scores, best_quality = list(chunks), list(scores), quality

            logger.info(
                "Corrective retrieval attempt completed",
                extra=log_extra(
                    user_id=context.user_id,
                    attempt=context.correction_attempts,
                    verdict=context.context_verdict,
                    quality=quality,
                ),
            )

        # Keep whichever attempt produced the strongest context.
        context.chunks = best_chunks
        context.chunk_scores = best_scores
        context.context_quality = round(best_quality, 4)
        context.metadata["correction_attempts"] = context.correction_attempts
        context.metadata["attempted_queries"] = len(context.attempted_queries)

    async def _rewrite_query(self, context: RagContext) -> str:
        """Ask the chat model for a better search query.

        A rewrite failure must never fail the request - returning an empty
        string simply ends the corrective loop and the original context is
        used, which is no worse than not having tried.
        """
        try:
            chat_model = LLMProviderFactory.create_chat_model(
                context.provider, context.model, temperature=0.0, max_tokens=100
            )
            response = await chat_model.ainvoke(
                [
                    SystemMessage(content=_REWRITE_SYSTEM_PROMPT),
                    HumanMessage(content=context.question),
                ]
            )
            rewritten = (response.content if isinstance(response.content, str) else str(response.content)).strip()
            # Guard against a model that ignores instructions and returns prose.
            if not rewritten or len(rewritten) > 300:
                return ""
            return rewritten.strip('"').strip()
        except Exception as exc:
            logger.warning(
                "Query rewrite failed; continuing with the original context",
                extra=log_extra(user_id=context.user_id, error=str(exc)),
            )
            return ""


class RerankStep(PipelineStep):
    """Order context by relevance, strongest first.

    Position matters: models attend more reliably to the start of a long
    context, so putting the best-matching chunk first is a cheap quality win
    that needs no cross-encoder or extra model call.
    """

    name = "rerank"

    async def run(self, context: RagContext) -> None:
        if not context.chunks or not context.chunk_scores:
            return
        if context.metadata.get("hybrid_ranked"):
            # Already ordered by Reciprocal Rank Fusion. Re-sorting by cosine
            # score here would throw away the keyword ranking - the whole
            # point of hybrid retrieval - so leave the order alone.
            return
        if len(context.chunks) != len(context.chunk_scores):
            # Defensive: never silently mis-pair chunks with scores.
            logger.warning("Skipping rerank: chunk/score length mismatch", extra=log_extra(user_id=context.user_id))
            return

        ordered = sorted(zip(context.chunks, context.chunk_scores), key=lambda pair: pair[1], reverse=True)
        context.chunks = [chunk for chunk, _ in ordered]
        context.chunk_scores = [score for _, score in ordered]

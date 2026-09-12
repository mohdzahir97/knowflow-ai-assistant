"""Generation step: turn retrieved context into a grounded answer."""
from __future__ import annotations

from typing import List, Tuple

from app.core.exceptions import ProviderError
from app.core.logging import get_logger, log_extra
from app.providers.llm import LLMProviderFactory
from app.rag.pipeline.base import PipelineStep
from app.rag.pipeline.context import RagContext
from app.rag.prompt_builder import NO_ANSWER_MESSAGE, PromptBuilder
from app.schemas.chat import SourceCitation, TokenUsage

logger = get_logger("app.rag.pipeline.generate")


class GenerateStep(PipelineStep):
    """Build the grounded prompt, call the chat model, collect citations.

    If nothing was retrieved there is nothing to ground an answer in, so this
    returns the fixed "not found" message instead of calling the model. That
    both preserves the application's core guarantee - never answer from
    outside the uploaded documents - and avoids paying for a call that
    could only hallucinate.
    """

    name = "generate"

    async def run(self, context: RagContext) -> None:
        if not context.chunks:
            context.answer = NO_ANSWER_MESSAGE
            context.sources = []
            context.halt("no_context_retrieved")
            logger.info("No context retrieved; returning the not-found response", extra=log_extra(user_id=context.user_id))
            return

        messages = PromptBuilder.build(context.chunks, context.question, context.history)
        chat_model = LLMProviderFactory.create_chat_model(
            context.provider,
            context.model,
            temperature=context.temperature,
            max_tokens=context.max_tokens,
        )

        try:
            response = await chat_model.ainvoke(messages)
        except Exception as exc:
            logger.error(
                "Chat provider call failed",
                extra=log_extra(user_id=context.user_id, provider=context.provider, error=str(exc)),
            )
            raise ProviderError(
                f"The '{context.provider}' provider failed to generate a response: {exc}"
            ) from exc

        context.answer = response.content if isinstance(response.content, str) else str(response.content)
        context.sources = self._build_sources(context)
        context.token_usage = self._extract_token_usage(response)

        logger.info(
            "Generation step completed",
            extra=log_extra(user_id=context.user_id, provider=context.provider, model=context.model),
        )

    @staticmethod
    def _build_sources(context: RagContext) -> List[SourceCitation]:
        """One citation per (document, page), in retrieval-rank order."""
        seen: set[Tuple[str, int]] = set()
        sources: List[SourceCitation] = []
        for chunk in context.chunks:
            filename = chunk.metadata.get("filename", "unknown")
            page = chunk.metadata.get("page", 0)
            key = (filename, page)
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                SourceCitation(document=filename, page=page, chunk_id=chunk.metadata.get("chunk_id", ""))
            )
        return sources

    @staticmethod
    def _extract_token_usage(response) -> TokenUsage | None:
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return None
        return TokenUsage(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )

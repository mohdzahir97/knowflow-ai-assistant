"""Answer verification: is the generated answer actually supported by context?

The final CRAG safeguard. The prompt instructs the model to answer only from
the supplied context, but instructions are not guarantees - this checks the
result rather than trusting it.

Costs one extra LLM call per answered question, which roughly doubles
latency on local models, so it is opt-in via CRAG_VERIFY_GROUNDEDNESS.
Skipped when the assistant already declined to answer: there is nothing to
verify about "I couldn't find that information".
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import get_settings
from app.core.logging import get_logger, log_extra
from app.providers.llm import LLMProviderFactory
from app.rag.pipeline.base import PipelineStep
from app.rag.pipeline.context import RagContext
from app.rag.prompt_builder import NO_ANSWER_MESSAGE, PromptBuilder

logger = get_logger("app.rag.pipeline.verify")

VERDICT_GROUNDED = "grounded"
VERDICT_UNGROUNDED = "ungrounded"
VERDICT_SKIPPED = "skipped"

_VERIFY_SYSTEM_PROMPT = """You check whether an answer is fully supported by the supplied context.

Reply with exactly one word:
- GROUNDED  - every factual claim in the answer appears in the context.
- UNGROUNDED - the answer contains any claim not supported by the context.

Judge only whether the claims are present in the context. Do not judge \
whether the answer is helpful, well written, or true in the wider world."""


class VerifyGroundednessStep(PipelineStep):
    """Replace an unsupported answer with the standard "not found" response.

    Failing closed is deliberate. The core promise of this application is
    that it never answers from outside the knowledge base, so an answer that
    cannot be verified is withheld rather than shown with a caveat.
    """

    name = "verify_groundedness"

    async def run(self, context: RagContext) -> None:
        settings = get_settings()

        if not settings.crag_verify_groundedness:
            context.groundedness_verdict = VERDICT_SKIPPED
            return

        # Nothing to verify: the assistant already declined, or produced nothing.
        if not context.answer or context.answer.strip() == NO_ANSWER_MESSAGE or not context.chunks:
            context.groundedness_verdict = VERDICT_SKIPPED
            return

        try:
            chat_model = LLMProviderFactory.create_chat_model(
                context.provider, context.model, temperature=0.0, max_tokens=10
            )
            response = await chat_model.ainvoke(
                [
                    SystemMessage(content=_VERIFY_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Context:\n{PromptBuilder.format_context(context.chunks)}\n\n"
                            f"Answer:\n{context.answer}"
                        )
                    ),
                ]
            )
            raw = (response.content if isinstance(response.content, str) else str(response.content)).strip().upper()
        except Exception as exc:
            # A verifier outage must not take the whole request down. Fail
            # open here (keep the answer) and say so, because failing closed
            # on an infrastructure error would silently suppress good
            # answers whenever the verifier is unavailable.
            logger.warning(
                "Groundedness check failed; keeping the answer unverified",
                extra=log_extra(user_id=context.user_id, error=str(exc)),
            )
            context.groundedness_verdict = VERDICT_SKIPPED
            return

        if raw.startswith("UNGROUNDED"):
            context.groundedness_verdict = VERDICT_UNGROUNDED
            context.metadata["suppressed_ungrounded_answer"] = True
            logger.warning(
                "Answer failed the groundedness check and was withheld",
                extra=log_extra(user_id=context.user_id, quality=context.context_quality),
            )
            context.answer = NO_ANSWER_MESSAGE
            context.sources = []
            return

        context.groundedness_verdict = VERDICT_GROUNDED
        logger.info("Answer verified as grounded", extra=log_extra(user_id=context.user_id))

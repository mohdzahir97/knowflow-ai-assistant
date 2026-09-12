"""Guardrail steps: input validation before retrieval, output checks after.

Placement in the pipeline is the point. The input guard runs FIRST, so a
rejected question never reaches retrieval or the model and costs nothing.
The output guard runs LAST, after generation and groundedness verification.

Deliberately NOT duplicated here:

* Hallucination / groundedness - already `VerifyGroundednessStep`.
* Context relevance - already `GradeContextStep`.
* Injection *inside retrieved documents* - handled structurally in
  `prompt_builder` (nonce-delimited untrusted block, neutralised
  scaffolding), which is stronger than pattern-matching document text and
  cannot be evaded by paraphrase.

Adding second implementations of those would be duplicate machinery with
extra cost and no extra safety.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.exceptions import ValidationAppError
from app.core.logging import get_logger, log_extra
from app.guardrails.detectors import (
    GuardrailResult,
    detect_harmful_content,
    detect_pii,
    detect_prompt_injection,
    redact_pii,
)
from app.rag.pipeline.base import PipelineStep
from app.rag.pipeline.context import RagContext
from app.rag.prompt_builder import NO_ANSWER_MESSAGE

logger = get_logger("app.guardrails")

REFUSAL_MESSAGE = "I can't help with that request."


class InputGuardrailStep(PipelineStep):
    """Validate and sanitise the question before anything expensive happens.

    Rejects outright only for genuinely unsafe intent. Prompt-injection
    attempts and PII are recorded and sanitised rather than refused: the
    structural defences already contain injection, and a user who happens to
    paste an email address into an otherwise reasonable question should get
    an answer, not a lecture.
    """

    name = "input_guardrail"

    async def run(self, context: RagContext) -> None:
        settings = get_settings()
        if not settings.guardrails_enabled:
            return

        question = context.question
        result = GuardrailResult()

        if len(question) > settings.guardrail_max_question_chars:
            # Checked before anything else: an oversized prompt is both a
            # cost problem and a way to push instructions past a context
            # window.
            raise ValidationAppError(
                f"Question is too long ({len(question)} characters). "
                f"Please keep it under {settings.guardrail_max_question_chars}."
            )

        for finding in detect_harmful_content(question):
            result.add(finding.category, finding.detail)
            result.allowed = False

        for finding in detect_prompt_injection(question):
            result.add(finding.category, finding.detail)

        pii_findings = detect_pii(question)
        for finding in pii_findings:
            result.add(finding.category, finding.detail)

        context.metadata["input_guardrail"] = result.categories

        if not result.allowed:
            logger.warning(
                "Question refused by input guardrail",
                extra=log_extra(user_id=context.user_id, categories=result.categories),
            )
            context.answer = REFUSAL_MESSAGE
            context.sources = []
            context.metadata["refused_by"] = "input_guardrail"
            context.halt("input_guardrail_refused")
            return

        if pii_findings and settings.guardrail_redact_pii_in_queries:
            # Redact before the question is embedded or sent to a provider,
            # so identifiers do not leave this process.
            context.search_query = redact_pii(context.search_query)
            logger.info(
                "Redacted PII from the search query",
                extra=log_extra(user_id=context.user_id, categories=[f.detail for f in pii_findings]),
            )

        if result.findings:
            logger.info(
                "Input guardrail findings",
                extra=log_extra(user_id=context.user_id, categories=result.categories),
            )


class OutputGuardrailStep(PipelineStep):
    """Final check on what is about to be shown to the user."""

    name = "output_guardrail"

    async def run(self, context: RagContext) -> None:
        settings = get_settings()
        if not settings.guardrails_enabled or not context.answer:
            return

        answer = context.answer

        # Nothing to inspect in the standard refusals.
        if answer.strip() in (NO_ANSWER_MESSAGE, REFUSAL_MESSAGE):
            return

        findings = detect_harmful_content(answer)
        if findings:
            logger.warning(
                "Answer withheld by output guardrail",
                extra=log_extra(user_id=context.user_id, categories=[f.category for f in findings]),
            )
            context.answer = REFUSAL_MESSAGE
            context.sources = []
            context.metadata["refused_by"] = "output_guardrail"
            return

        if settings.guardrail_redact_pii_in_answers:
            pii_findings = detect_pii(answer)
            if pii_findings:
                # An answer can only contain PII that was in a document, but
                # surfacing it in chat widens who sees it.
                context.answer = redact_pii(answer)
                context.metadata["output_pii_redacted"] = [f.detail for f in pii_findings]
                logger.info(
                    "Redacted PII from the answer",
                    extra=log_extra(user_id=context.user_id, categories=[f.detail for f in pii_findings]),
                )

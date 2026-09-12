"""Assembles the Corrective RAG pipeline.

Isolating construction here means the pipeline's shape is described in one
readable place, and later phases extend the application by editing this list
rather than by modifying ChatService. Guardrail steps slot into the same
sequence.
"""
from __future__ import annotations

from functools import lru_cache

from app.rag.pipeline.base import Pipeline
from app.rag.pipeline.steps.correct import CorrectiveRetrievalStep, RerankStep
from app.rag.pipeline.steps.generate import GenerateStep
from app.rag.pipeline.steps.grade import GradeContextStep
from app.rag.pipeline.steps.guardrails import InputGuardrailStep, OutputGuardrailStep
from app.rag.pipeline.steps.retrieve import RetrieveStep
from app.rag.pipeline.steps.verify import VerifyGroundednessStep


def _retrieval_steps() -> list:
    """Everything up to, but excluding, generation.

    Shared by the buffered and streaming paths so the two cannot drift:
    streaming needs to run retrieval to completion, then hand the context to
    a token generator, which means it must stop short of `generate`.
    """
    return [
        # First: a refused question must never reach retrieval or a model.
        InputGuardrailStep(),
        RetrieveStep(),
        GradeContextStep(),
        CorrectiveRetrievalStep(),
        RerankStep(),
    ]


def build_retrieval_pipeline() -> Pipeline:
    """Retrieval only - used by the streaming endpoint, which generates
    tokens itself so it can emit them as they arrive."""
    return Pipeline(_retrieval_steps())


def build_rag_pipeline() -> Pipeline:
    """The Corrective RAG question-answering pipeline.

        retrieve            vector search (scored, de-duplicated)
        grade_context       is this context good enough to answer from?
        corrective_retrieval  if not: rewrite the query and retry (bounded)
        rerank              strongest context first
        generate            grounded answer, or the "not found" response
        verify_groundedness  withhold answers not supported by context

    Only `generate` and, when enabled, `verify_groundedness` call the model
    on a normal request. The rewrite inside `corrective_retrieval` runs
    solely when grading fails, so a well-matched question costs exactly what
    it did before Corrective RAG existed.

    Steps are stateless, so one pipeline instance serves concurrent
    requests; all per-request state lives in RagContext.
    """
    return Pipeline([*_retrieval_steps(), GenerateStep(), VerifyGroundednessStep(), OutputGuardrailStep()])


@lru_cache(maxsize=1)
def get_rag_pipeline() -> Pipeline:
    return build_rag_pipeline()


@lru_cache(maxsize=1)
def get_retrieval_pipeline() -> Pipeline:
    return build_retrieval_pipeline()

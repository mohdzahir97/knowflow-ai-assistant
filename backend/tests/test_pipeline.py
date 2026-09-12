"""The Pipeline/Step abstraction.

Corrective RAG and the guardrail chain are both built on these guarantees,
so they are pinned here with plain in-memory steps rather than through the
API - if ordering, short-circuiting or timing ever break, the failure should
point at this file rather than at whichever feature noticed.
"""
import asyncio
from typing import List

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.rag.pipeline import Pipeline, PipelineStep, RagContext, build_rag_pipeline


class _NullEmbeddings(Embeddings):
    def embed_documents(self, texts):  # pragma: no cover - never called here
        return [[0.0] for _ in texts]

    def embed_query(self, text):  # pragma: no cover - never called here
        return [0.0]


def make_context(**overrides) -> RagContext:
    defaults = dict(
        question="What is the leave policy?",
        user_id="user-1",
        embedding_provider="testembed",
        embedding_model="fake-embed-model",
        embeddings=_NullEmbeddings(),
        provider="testchat",
        model="fake-model",
    )
    defaults.update(overrides)
    return RagContext(**defaults)


class RecordingStep(PipelineStep):
    def __init__(self, name: str, log: List[str]) -> None:
        self.name = name
        self._log = log

    async def run(self, context: RagContext) -> None:
        self._log.append(self.name)


class HaltingStep(PipelineStep):
    name = "halting"

    def __init__(self, log: List[str]) -> None:
        self._log = log

    async def run(self, context: RagContext) -> None:
        self._log.append(self.name)
        context.halt("stopped_for_test")


class ExplodingStep(PipelineStep):
    name = "exploding"

    async def run(self, context: RagContext) -> None:
        raise RuntimeError("step failed")


class SlowStep(PipelineStep):
    name = "slow"

    async def run(self, context: RagContext) -> None:
        await asyncio.sleep(0.05)


def test_search_query_defaults_to_the_question():
    """Query rewriting replaces search_query; question must stay pristine so
    citations and logs always reflect what the user actually asked."""
    context = make_context()
    assert context.search_query == context.question


def test_steps_run_in_declared_order():
    log: List[str] = []
    pipeline = Pipeline([RecordingStep("a", log), RecordingStep("b", log), RecordingStep("c", log)])
    asyncio.run(pipeline.run(make_context()))
    assert log == ["a", "b", "c"]


def test_halting_skips_remaining_steps():
    """The mechanism Corrective RAG relies on to answer 'not found' without
    calling the model."""
    log: List[str] = []
    pipeline = Pipeline([RecordingStep("first", log), HaltingStep(log), RecordingStep("never", log)])
    context = asyncio.run(pipeline.run(make_context()))

    assert log == ["first", "halting"]
    assert context.halted is True
    assert context.halt_reason == "stopped_for_test"


def test_step_errors_propagate_and_are_still_timed():
    """A failing step must not be silently swallowed, but its cost should
    still show up so slow failures are diagnosable."""
    pipeline = Pipeline([ExplodingStep()])
    context = make_context()
    with pytest.raises(RuntimeError, match="step failed"):
        asyncio.run(pipeline.run(context))
    assert "exploding" in context.step_timings_ms


def test_timings_are_recorded_per_step():
    context = asyncio.run(Pipeline([SlowStep()]).run(make_context()))
    assert context.timing_for("slow") >= 45  # ~50ms sleep, allowing jitter


def test_repeated_step_timings_accumulate():
    """Corrective retrieval re-runs the retrieve step; the second run must
    add to the first rather than hide it."""
    context = make_context()
    context.record_timing("retrieve", 100.0)
    context.record_timing("retrieve", 50.0)
    assert context.timing_for("retrieve") == 150.0


def test_timing_for_unknown_step_is_zero():
    """Response timings read step names directly, so a step that never ran
    must report 0 rather than raise."""
    assert make_context().timing_for("not-a-step") == 0.0


def test_default_pipeline_shape():
    """Guards the documented order; later phases insert steps between these."""
    assert [step.name for step in build_rag_pipeline().steps] == [
        # Input guard first: a refused question costs no retrieval and no
        # model call. Output guard last: it inspects the final answer.
        "input_guardrail",
        "retrieve",
        "grade_context",
        "corrective_retrieval",
        "rerank",
        "generate",
        "verify_groundedness",
        "output_guardrail",
    ]


def test_generate_step_halts_when_no_context_retrieved():
    """The application's core guarantee: with nothing retrieved, return the
    fixed not-found message instead of asking the model to invent one."""
    from app.rag.pipeline.steps.generate import GenerateStep
    from app.rag.prompt_builder import NO_ANSWER_MESSAGE

    context = make_context()
    context.chunks = []
    asyncio.run(GenerateStep().run(context))

    assert context.answer == NO_ANSWER_MESSAGE
    assert context.sources == []
    assert context.halted is True
    assert context.halt_reason == "no_context_retrieved"


def test_generate_step_deduplicates_citations_by_document_and_page():
    from app.rag.pipeline.steps.generate import GenerateStep

    context = make_context()
    context.chunks = [
        Document(page_content="a", metadata={"filename": "h.pdf", "page": 1, "chunk_id": "c1"}),
        Document(page_content="b", metadata={"filename": "h.pdf", "page": 1, "chunk_id": "c2"}),
        Document(page_content="c", metadata={"filename": "h.pdf", "page": 2, "chunk_id": "c3"}),
    ]
    sources = GenerateStep._build_sources(context)

    assert [(s.document, s.page) for s in sources] == [("h.pdf", 1), ("h.pdf", 2)]

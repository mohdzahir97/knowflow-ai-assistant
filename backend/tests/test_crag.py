"""Corrective RAG: grading, correction, re-ranking and verification.

Each step is exercised directly against a RagContext rather than through the
API, so a failure names the step that broke. The end-to-end behaviour is
covered separately by the chat API tests.
"""
import asyncio
from typing import List, Optional, Tuple

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.core.config import get_settings
from app.providers.llm.base import BaseChatProvider
from app.providers.llm.factory import LLMProviderFactory
from app.rag.pipeline.context import RagContext
from app.rag.pipeline.steps.correct import CorrectiveRetrievalStep, RerankStep
from app.rag.pipeline.steps.grade import VERDICT_GOOD, VERDICT_POOR, GradeContextStep
from app.rag.pipeline.steps.verify import (
    VERDICT_GROUNDED,
    VERDICT_SKIPPED,
    VERDICT_UNGROUNDED,
    VerifyGroundednessStep,
)
from app.rag.prompt_builder import NO_ANSWER_MESSAGE


class _NullEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[0.0] for _ in texts]

    def embed_query(self, text):
        return [0.0]


def make_context(**overrides) -> RagContext:
    defaults = dict(
        question="What is the leave policy?",
        user_id="user-1",
        embedding_provider="testembed",
        embedding_model="fake-embed-model",
        embeddings=_NullEmbeddings(),
        provider="cragchat",
        model="fake-model",
    )
    defaults.update(overrides)
    return RagContext(**defaults)


def chunk(text: str, page: int = 1) -> Document:
    return Document(page_content=text, metadata={"filename": "kb.pdf", "page": page, "chunk_id": f"c{page}"})


class _ScriptedChatModel(BaseChatModel):
    """Returns queued replies in order, so a test can drive rewrite/verify."""

    replies: List[str] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        reply = _ScriptedChatModel.replies.pop(0) if _ScriptedChatModel.replies else "fallback"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reply))])

    @property
    def _llm_type(self) -> str:
        return "scripted"


@LLMProviderFactory.register("cragchat")
class _CragChatProvider(BaseChatProvider):
    display_name = "CRAG Test Chat"
    default_models = ["fake-model"]

    def _api_key(self) -> str:
        return "fake-key"

    def _build(self, model: str, temperature: float, max_tokens: int) -> BaseChatModel:
        return _ScriptedChatModel()


class _StubRetriever:
    """Returns a queued (chunks, scores) result per retrieval call."""

    def __init__(self, results: List[Tuple[List[Document], List[float]]]) -> None:
        self._results = list(results)
        self.queries: List[str] = []

    async def aretrieve_scored(self, *, query: str, **kwargs):
        self.queries.append(query)
        return self._results.pop(0) if self._results else ([], [])


@pytest.fixture(autouse=True)
def _reset_scripted_model():
    _ScriptedChatModel.replies = []
    yield
    _ScriptedChatModel.replies = []


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def test_strong_scores_grade_as_good():
    context = make_context()
    context.chunks = [chunk("leave policy text")]
    context.chunk_scores = [0.34]  # measured value for an on-topic query
    asyncio.run(GradeContextStep().run(context))

    assert context.context_verdict == VERDICT_GOOD
    assert context.context_quality == 0.34


def test_weak_scores_grade_as_poor():
    context = make_context()
    context.chunks = [chunk("unrelated text")]
    context.chunk_scores = [0.10]  # measured value for an off-topic query
    asyncio.run(GradeContextStep().run(context))

    assert context.context_verdict == VERDICT_POOR


def test_empty_retrieval_grades_as_poor():
    context = make_context()
    asyncio.run(GradeContextStep().run(context))

    assert context.context_verdict == VERDICT_POOR
    assert context.context_quality == 0.0


def test_grading_costs_no_llm_call():
    """Grading is score-based by design; if it ever starts calling a model
    this test fails because no reply is queued."""
    context = make_context()
    context.chunks = [chunk("text")]
    context.chunk_scores = [0.9]
    asyncio.run(GradeContextStep().run(context))
    assert context.context_verdict == VERDICT_GOOD


# ---------------------------------------------------------------------------
# Corrective retrieval
# ---------------------------------------------------------------------------


def test_good_context_skips_correction_entirely():
    """The cost guarantee: a well-matched question must not pay for a rewrite."""
    retriever = _StubRetriever([])
    context = make_context()
    context.context_verdict = VERDICT_GOOD
    context.chunks = [chunk("good")]
    context.chunk_scores = [0.5]

    asyncio.run(CorrectiveRetrievalStep(retriever=retriever).run(context))

    assert retriever.queries == [], "no re-retrieval should happen"
    assert context.correction_attempts == 0


def test_poor_context_triggers_rewrite_and_retry():
    _ScriptedChatModel.replies = ["employment at will policy"]
    better = ([chunk("employment at will clause")], [0.42])
    retriever = _StubRetriever([better])

    context = make_context()
    context.context_verdict = VERDICT_POOR
    context.chunks = [chunk("weak")]
    context.chunk_scores = [0.10]
    context.attempted_queries = [context.question]

    asyncio.run(CorrectiveRetrievalStep(retriever=retriever).run(context))

    assert context.correction_attempts == 1
    assert retriever.queries == ["employment at will policy"]
    assert context.context_verdict == VERDICT_GOOD
    assert context.context_quality == 0.42
    # The user's original wording must survive for citations and logging.
    assert context.question == "What is the leave policy?"


def test_correction_keeps_the_better_of_the_two_attempts():
    """A rewrite that retrieves *worse* context must be discarded, not taken."""
    _ScriptedChatModel.replies = ["a worse query"]
    worse = ([chunk("worse")], [0.05])
    retriever = _StubRetriever([worse])

    context = make_context()
    context.context_verdict = VERDICT_POOR
    context.chunks = [chunk("original")]
    context.chunk_scores = [0.20]
    context.attempted_queries = [context.question]

    asyncio.run(CorrectiveRetrievalStep(retriever=retriever).run(context))

    assert context.context_quality == 0.20, "should keep the stronger original context"
    assert context.chunks[0].page_content == "original"


def test_correction_is_bounded_by_configuration(monkeypatch):
    """A hopeless query must not loop indefinitely."""
    monkeypatch.setattr(get_settings(), "crag_max_correction_attempts", 2)
    _ScriptedChatModel.replies = ["rewrite one", "rewrite two", "rewrite three"]
    poor = ([chunk("still bad")], [0.05])
    retriever = _StubRetriever([poor, poor, poor])

    context = make_context()
    context.context_verdict = VERDICT_POOR
    context.chunks = [chunk("bad")]
    context.chunk_scores = [0.05]
    context.attempted_queries = [context.question]

    asyncio.run(CorrectiveRetrievalStep(retriever=retriever).run(context))

    assert context.correction_attempts == 2
    assert len(retriever.queries) == 2


def test_rewrite_failure_leaves_the_request_working():
    """A rewrite outage must degrade to the original context, not an error."""
    _ScriptedChatModel.replies = [""]  # empty rewrite
    retriever = _StubRetriever([])

    context = make_context()
    context.context_verdict = VERDICT_POOR
    context.chunks = [chunk("original")]
    context.chunk_scores = [0.15]
    context.attempted_queries = [context.question]

    asyncio.run(CorrectiveRetrievalStep(retriever=retriever).run(context))

    assert context.chunks[0].page_content == "original"
    assert retriever.queries == []


def test_correction_disabled_by_configuration(monkeypatch):
    monkeypatch.setattr(get_settings(), "crag_enabled", False)
    retriever = _StubRetriever([])

    context = make_context()
    context.context_verdict = VERDICT_POOR
    context.chunks = [chunk("weak")]
    context.chunk_scores = [0.05]

    asyncio.run(CorrectiveRetrievalStep(retriever=retriever).run(context))
    assert context.correction_attempts == 0


# ---------------------------------------------------------------------------
# Re-ranking
# ---------------------------------------------------------------------------


def test_rerank_orders_strongest_context_first():
    context = make_context()
    context.chunks = [chunk("weak", 1), chunk("strong", 2), chunk("middle", 3)]
    context.chunk_scores = [0.10, 0.90, 0.50]

    asyncio.run(RerankStep().run(context))

    assert [c.page_content for c in context.chunks] == ["strong", "middle", "weak"]
    assert context.chunk_scores == [0.90, 0.50, 0.10]


def test_rerank_is_safe_when_scores_are_missing():
    context = make_context()
    context.chunks = [chunk("a"), chunk("b")]
    context.chunk_scores = []
    asyncio.run(RerankStep().run(context))
    assert len(context.chunks) == 2  # unchanged, no exception


# ---------------------------------------------------------------------------
# Groundedness verification
# ---------------------------------------------------------------------------


def test_verification_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "crag_verify_groundedness", False)
    context = make_context()
    context.answer = "Employees get 20 days."
    context.chunks = [chunk("20 days of leave")]

    asyncio.run(VerifyGroundednessStep().run(context))
    assert context.groundedness_verdict == VERDICT_SKIPPED
    assert context.answer == "Employees get 20 days."


def test_grounded_answer_is_kept(monkeypatch):
    monkeypatch.setattr(get_settings(), "crag_verify_groundedness", True)
    _ScriptedChatModel.replies = ["GROUNDED"]

    context = make_context()
    context.answer = "Employees get 20 days."
    context.chunks = [chunk("Employees get 20 days of paid leave.")]

    asyncio.run(VerifyGroundednessStep().run(context))
    assert context.groundedness_verdict == VERDICT_GROUNDED
    assert context.answer == "Employees get 20 days."


def test_ungrounded_answer_is_withheld(monkeypatch):
    """Fails closed: an unsupported answer is replaced, not annotated."""
    monkeypatch.setattr(get_settings(), "crag_verify_groundedness", True)
    _ScriptedChatModel.replies = ["UNGROUNDED"]

    context = make_context()
    context.answer = "Employees get 40 days and a company car."
    context.chunks = [chunk("Employees get 20 days of paid leave.")]
    context.sources = []

    asyncio.run(VerifyGroundednessStep().run(context))

    assert context.groundedness_verdict == VERDICT_UNGROUNDED
    assert context.answer == NO_ANSWER_MESSAGE
    assert context.sources == []


def test_verification_skipped_for_the_not_found_response(monkeypatch):
    """Nothing to verify, and no reason to pay for a call."""
    monkeypatch.setattr(get_settings(), "crag_verify_groundedness", True)
    context = make_context()
    context.answer = NO_ANSWER_MESSAGE
    context.chunks = [chunk("something")]

    asyncio.run(VerifyGroundednessStep().run(context))
    assert context.groundedness_verdict == VERDICT_SKIPPED


def test_verifier_outage_fails_open(monkeypatch):
    """An infrastructure failure must not suppress a good answer."""
    monkeypatch.setattr(get_settings(), "crag_verify_groundedness", True)

    class _Boom(VerifyGroundednessStep):
        pass

    context = make_context(provider="does-not-exist")
    context.answer = "A real answer."
    context.chunks = [chunk("supporting text")]

    asyncio.run(_Boom().run(context))

    assert context.groundedness_verdict == VERDICT_SKIPPED
    assert context.answer == "A real answer."

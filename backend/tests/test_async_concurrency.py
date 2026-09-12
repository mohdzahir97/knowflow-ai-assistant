"""Proves the async migration actually buys concurrency.

The point of making the RAG path async was that a synchronous handler pinned
a threadpool worker for the entire model call, so N slow questions took N x
the model latency. These tests fire overlapping requests against a provider
with a deliberate delay and assert the total wall time looks concurrent
rather than serial.

Thresholds are deliberately loose - this asserts "clearly overlapping", not
a precise speedup, so it does not become a flaky timing test.
"""
import asyncio
import time
from typing import List

import httpx
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.providers.llm.base import BaseChatProvider
from app.providers.llm.factory import LLMProviderFactory

# How long the fake model "spends" generating, and how many questions overlap.
#
# The delay is set to a realistic model latency (~1s) rather than something
# tiny on purpose. ChromaDB's persistent client is SQLite-backed, so
# concurrent vector searches queue against its internal store and contribute
# a roughly serial floor (measured: ~80ms per additional concurrent search).
# With a very fast model that fixed retrieval cost dominates the measurement
# and hides the concurrency that this test exists to prove.
_DELAY_SECONDS = 1.0
_CONCURRENCY = 5


class SlowAsyncChatModel(BaseChatModel):
    """Mimics a real provider: native async that awaits network I/O.

    Implementing _agenerate (rather than only _generate) is what real
    providers such as ChatOpenAI/ChatGroq/ChatOllama do, and is what allows
    the event loop to interleave requests.
    """

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        time.sleep(_DELAY_SECONDS)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="slow answer"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        await asyncio.sleep(_DELAY_SECONDS)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="slow answer"))])

    @property
    def _llm_type(self) -> str:
        return "slow-async"


@LLMProviderFactory.register("slowchat")
class SlowChatProvider(BaseChatProvider):
    display_name = "Slow Async Test Chat"
    default_models = ["slow-model"]

    def _api_key(self) -> str:
        return "fake-key"

    def _build(self, model: str, temperature: float, max_tokens: int) -> BaseChatModel:
        return SlowAsyncChatModel()


@pytest.fixture(autouse=True)
def _isolate_from_crag(monkeypatch):
    """Measure request overlap, not Corrective RAG.

    The fake embeddings used in tests produce low relevance scores, so CRAG
    correctly judges the context poor and performs a corrective round - an
    extra rewrite call plus a second retrieval per request. That is right
    behaviour but it is confounding work for a test whose subject is whether
    the async handler interleaves requests at all.
    """
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "crag_enabled", False)


@pytest.fixture
def indexed_user(client, auth_headers, admin_headers, sample_pdf_bytes) -> dict:
    """An end user asking against a knowledge base an admin has populated."""
    response = client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files={"files": ("sample.pdf", sample_pdf_bytes, "application/pdf")},
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    assert response.status_code == 201, response.text
    return auth_headers


def _ask_payload(question: str) -> dict:
    return {
        "question": question,
        "provider": "slowchat",
        "model": "slow-model",
        "embedding_provider": "testembed",
        "embedding_model": "fake-embed-model",
    }


@pytest.mark.anyio
async def test_concurrent_questions_overlap(indexed_user):
    """N overlapping questions must cost far less than N sequential ones.

    The baseline is *measured in this same run* rather than assumed from
    _DELAY_SECONDS. An earlier version compared against a theoretical
    N x delay and was flaky (~1 run in 3): under full-suite load, ChromaDB
    contention adds a variable serial component that has nothing to do with
    whether the handler awaits properly. Timing one real request first
    calibrates to the machine's current state, so the assertion measures
    overlap and not ambient load.
    """
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:

        async def ask(index: int) -> httpx.Response:
            return await async_client.post(
                "/api/v1/chat/ask",
                headers=indexed_user,
                json=_ask_payload(f"paid leave question {index}"),
                timeout=60.0,
            )

        # One request alone: the real cost of a single question right now.
        started = time.perf_counter()
        warmup = await ask(0)
        single_duration = time.perf_counter() - started
        assert warmup.status_code == 200, warmup.text

        started = time.perf_counter()
        responses: List[httpx.Response] = await asyncio.gather(
            *(ask(index) for index in range(1, _CONCURRENCY + 1))
        )
        concurrent_duration = time.perf_counter() - started

    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]

    sequential_estimate = single_duration * _CONCURRENCY
    # Blocking would make the concurrent batch cost about the sequential
    # estimate. Anything comfortably below it proves requests interleaved;
    # 0.7 tolerates contention while still failing loudly on a regression to
    # synchronous handling (which measured ~3.3x slower).
    assert concurrent_duration < sequential_estimate * 0.7, (
        f"{_CONCURRENCY} concurrent questions took {concurrent_duration:.2f}s; "
        f"one alone took {single_duration:.2f}s, so sequential would be "
        f"~{sequential_estimate:.2f}s - these did not overlap"
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"

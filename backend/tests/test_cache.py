"""Bounded TTL cache and query-embedding caching."""
import time

import pytest
from langchain_core.embeddings import Embeddings

from app.core.cache import TTLCache
from app.core.config import get_settings
from app.providers.embeddings.caching import CachingEmbeddings, get_query_cache


class CountingEmbeddings(Embeddings):
    """Records how often the underlying model was actually asked."""

    def __init__(self) -> None:
        self.query_calls = 0
        self.document_calls = 0

    def embed_documents(self, texts):
        self.document_calls += 1
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        self.query_calls += 1
        return [float(len(text)), 0.0]

    async def aembed_query(self, text):
        self.query_calls += 1
        return [float(len(text)), 0.0]


# ---------------------------------------------------------------------------
# TTLCache
# ---------------------------------------------------------------------------


def test_returns_what_was_stored():
    cache = TTLCache()
    cache.set("k", [1, 2, 3])
    assert cache.get("k") == [1, 2, 3]


def test_missing_key_is_a_miss():
    assert TTLCache().get("nope") is None


def test_entries_expire():
    cache = TTLCache(ttl_seconds=0.2)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    time.sleep(0.3)
    assert cache.get("k") is None, "expired entry was served"


def test_cache_is_bounded_and_evicts_the_least_recently_used():
    """An unbounded cache keyed by user input is a memory leak."""
    cache = TTLCache(max_entries=3)
    for key in ["a", "b", "c"]:
        cache.set(key, key)

    cache.get("a")  # 'a' is now the most recently used, so 'b' is the victim
    cache.set("d", "d")

    assert cache.size == 3
    assert cache.get("b") is None
    assert cache.get("a") == "a"
    assert cache.get("d") == "d"


def test_get_or_set_computes_only_once():
    cache = TTLCache()
    calls = []

    def factory():
        calls.append(1)
        return "value"

    assert cache.get_or_set("k", factory) == "value"
    assert cache.get_or_set("k", factory) == "value"
    assert len(calls) == 1


def test_stats_report_hit_rate():
    cache = TTLCache()
    cache.set("k", "v")
    cache.get("k")
    cache.get("absent")
    stats = cache.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_clear_empties_the_cache():
    cache = TTLCache()
    cache.set("k", "v")
    cache.clear()
    assert cache.size == 0 and cache.get("k") is None


# ---------------------------------------------------------------------------
# Query embedding cache
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_query_cache():
    get_query_cache().clear()
    yield
    get_query_cache().clear()


def test_repeat_question_does_not_re_embed():
    inner = CountingEmbeddings()
    embeddings = CachingEmbeddings(inner, "testembed", "fake-embed-model")

    first = embeddings.embed_query("what is the leave policy?")
    second = embeddings.embed_query("what is the leave policy?")

    assert first == second
    assert inner.query_calls == 1, "the model was asked twice for the same question"


def test_different_questions_are_embedded_separately():
    inner = CountingEmbeddings()
    embeddings = CachingEmbeddings(inner, "testembed", "fake-embed-model")
    embeddings.embed_query("question one")
    embeddings.embed_query("a different question")
    assert inner.query_calls == 2


def test_the_same_text_under_a_different_model_is_not_shared():
    """Serving one model's vector to another would corrupt retrieval."""
    inner_a, inner_b = CountingEmbeddings(), CountingEmbeddings()
    a = CachingEmbeddings(inner_a, "testembed", "model-a")
    b = CachingEmbeddings(inner_b, "testembed", "model-b")

    a.embed_query("same text")
    b.embed_query("same text")

    assert inner_a.query_calls == 1
    assert inner_b.query_calls == 1, "a different model's cached vector was reused"


def test_the_same_text_under_a_different_provider_is_not_shared():
    inner_a, inner_b = CountingEmbeddings(), CountingEmbeddings()
    a = CachingEmbeddings(inner_a, "provider-a", "same-model")
    b = CachingEmbeddings(inner_b, "provider-b", "same-model")

    a.embed_query("same text")
    b.embed_query("same text")

    assert inner_b.query_calls == 1


def test_document_embedding_is_not_cached():
    """Chunk text is unique per document; caching it would only waste memory."""
    inner = CountingEmbeddings()
    embeddings = CachingEmbeddings(inner, "testembed", "fake-embed-model")

    embeddings.embed_documents(["chunk"])
    embeddings.embed_documents(["chunk"])

    assert inner.document_calls == 2


@pytest.mark.anyio
async def test_async_path_is_cached_too():
    """The chat pipeline is async, so this is the path that actually runs."""
    inner = CountingEmbeddings()
    embeddings = CachingEmbeddings(inner, "testembed", "fake-embed-model")

    await embeddings.aembed_query("repeated")
    await embeddings.aembed_query("repeated")

    assert inner.query_calls == 1


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_caching_can_be_disabled(monkeypatch):
    from app.providers.embeddings.caching import maybe_cache

    monkeypatch.setattr(get_settings(), "embedding_cache_enabled", False)
    inner = CountingEmbeddings()
    assert maybe_cache(inner, "p", "m") is inner


def test_provider_factory_returns_cached_embeddings(client):
    """The wrapping happens in the factory, so every consumer benefits."""
    from app.providers.embeddings.factory import EmbeddingProviderFactory

    embeddings = EmbeddingProviderFactory.create_embeddings("testembed", "fake-embed-model")
    assert isinstance(embeddings, CachingEmbeddings)


def test_a_real_question_populates_the_cache(client, auth_headers, admin_headers, sample_pdf_bytes):
    """End-to-end: asking twice consults the cache the second time."""
    client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files=[("files", ("cached.pdf", sample_pdf_bytes, "application/pdf"))],
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    payload = {
        "question": "what is the paid leave policy?",
        "provider": "testchat",
        "model": "fake-model",
        "embedding_provider": "testembed",
        "embedding_model": "fake-embed-model",
    }
    get_query_cache().clear()

    client.post("/api/v1/chat/ask", headers=auth_headers, json=payload)
    after_first = get_query_cache().stats()
    client.post("/api/v1/chat/ask", headers=auth_headers, json=payload)
    after_second = get_query_cache().stats()

    assert after_first["entries"] >= 1, "the question was never cached"
    assert after_second["hits"] > after_first["hits"], "the repeat question did not hit the cache"

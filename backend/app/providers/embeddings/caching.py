"""Caches query embeddings.

Embedding the question is the single slowest step before an answer can
begin - several seconds on a local CPU model - and it is a pure function of
(provider, model, text). Repeat questions are common in a company knowledge
assistant, so caching turns the second ask of "what is the leave policy?"
from seconds into a dictionary lookup.

Only `embed_query` is cached. `embed_documents` is called once per chunk
during indexing, with text that by definition has not been seen before;
caching it would fill memory to no purpose.
"""
from __future__ import annotations

from typing import List

from langchain_core.embeddings import Embeddings

from app.core.cache import TTLCache
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("app.embeddings.cache")

# Module-level so it is shared by every request, which is the entire point.
_query_cache = TTLCache(max_entries=1024, ttl_seconds=3600.0)


def get_query_cache() -> TTLCache:
    return _query_cache


class CachingEmbeddings(Embeddings):
    """Wraps an Embeddings instance, memoizing `embed_query`.

    Keyed by provider and model as well as text: two models return different
    vectors for identical input, and serving one model's vector to another
    would silently corrupt retrieval.
    """

    def __init__(self, inner: Embeddings, provider: str, model: str) -> None:
        self._inner = inner
        self._provider = provider
        self._model = model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return _query_cache.get_or_set(
            (self._provider, self._model, text), lambda: self._inner.embed_query(text)
        )

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await self._inner.aembed_documents(texts)

    async def aembed_query(self, text: str) -> List[float]:
        """The async path matters most - it is what the chat pipeline uses."""
        key = (self._provider, self._model, text)
        cached = _query_cache.get(key)
        if cached is not None:
            return cached
        vector = await self._inner.aembed_query(text)
        _query_cache.set(key, vector)
        return vector


def maybe_cache(inner: Embeddings, provider: str, model: str) -> Embeddings:
    """Wraps `inner` unless query caching is disabled in settings."""
    if not get_settings().embedding_cache_enabled:
        return inner
    return CachingEmbeddings(inner, provider, model)

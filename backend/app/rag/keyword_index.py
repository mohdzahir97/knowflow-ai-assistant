"""BM25 keyword index over the shared knowledge base.

Why this exists
---------------
Vector search matches on meaning, which fails in a specific and common way:
a query naming an exact phrase ("Employment at Will") can rank a
table-of-contents page - which merely mentions the heading - above the
section that actually contains the policy, because both are topically
similar. Keyword search does not have that failure mode, so the two are
complementary and are fused rather than chosen between.

Chroma has a native hybrid search, but as of chromadb 1.5.9 it is
documented as "experimental ... only works for distributed and hosted
Chroma", and this deployment uses the embedded PersistentClient. Hence a
local BM25 index.

Cost and invalidation
---------------------
The index is built from the chunk text already stored in Chroma, so it adds
no new source of truth - only a derived cache. It is rebuilt lazily on first
use and discarded whenever the knowledge base changes, because a stale
keyword index would silently return deleted documents.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document

from app.core.logging import get_logger, log_extra

logger = get_logger("app.rag.keyword_index")

# Deliberately simple: lowercase alphanumeric word tokens. BM25 needs
# consistent tokenisation far more than it needs linguistic sophistication,
# and a dependency-free tokeniser keeps behaviour predictable across
# platforms.
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    return _TOKEN_PATTERN.findall(text.lower())


@dataclass
class _IndexEntry:
    bm25: object
    documents: List[Document]


class KeywordIndex:
    """Lazily-built, invalidatable BM25 index, one per collection.

    Thread-safe: FastAPI serves requests from a threadpool and the event
    loop, so build and invalidate can race without the lock.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, _IndexEntry] = {}
        self._lock = threading.Lock()

    def invalidate(self, collection_name: Optional[str] = None) -> None:
        """Drop cached indexes. Called whenever documents change.

        Invalidating everything when no collection is named is the safe
        default: over-invalidating costs one rebuild, while under-
        invalidating serves deleted content.
        """
        with self._lock:
            if collection_name is None:
                count = len(self._entries)
                self._entries.clear()
            else:
                count = 1 if self._entries.pop(collection_name, None) else 0
        if count:
            logger.info("Keyword index invalidated", extra=log_extra(collections=count))

    def search(self, collection_name: str, documents: List[Document], query: str, top_k: int) -> List[Tuple[Document, float]]:
        """Return the best keyword matches, highest BM25 score first.

        `documents` is the full chunk set for the collection; it is used to
        build the index on a cache miss and ignored on a hit.
        """
        query_tokens = tokenize(query)
        if not query_tokens or not documents:
            return []

        entry = self._get_or_build(collection_name, documents)
        scores = entry.bm25.get_scores(query_tokens)

        ranked = sorted(zip(entry.documents, scores), key=lambda pair: pair[1], reverse=True)
        # BM25 scores 0 for documents sharing no query term; those are not
        # matches and must not pad the results.
        return [(document, float(score)) for document, score in ranked[:top_k] if score > 0]

    def _get_or_build(self, collection_name: str, documents: List[Document]) -> _IndexEntry:
        with self._lock:
            entry = self._entries.get(collection_name)
            if entry is not None and len(entry.documents) == len(documents):
                return entry

        # Build outside the lock: tokenising a large corpus is slow, and
        # blocking every reader for the duration would be worse than the
        # rare duplicated build a concurrent miss can cause.
        from rank_bm25 import BM25Okapi

        corpus = [tokenize(document.page_content) for document in documents]
        # BM25Okapi rejects an empty corpus, and a chunk with no tokens would
        # skew the average document length.
        usable = [(tokens, document) for tokens, document in zip(corpus, documents) if tokens]
        if not usable:
            return _IndexEntry(bm25=_EmptyBM25(), documents=[])

        tokens_list = [tokens for tokens, _ in usable]
        kept_documents = [document for _, document in usable]
        entry = _IndexEntry(bm25=BM25Okapi(tokens_list), documents=kept_documents)

        with self._lock:
            self._entries[collection_name] = entry
        logger.info(
            "Keyword index built",
            extra=log_extra(collection=collection_name, indexed_chunks=len(kept_documents)),
        )
        return entry


class _EmptyBM25:
    """Stand-in so an empty corpus behaves like "no matches" rather than raising."""

    def get_scores(self, _tokens: List[str]):  # pragma: no cover - trivial
        return []


_keyword_index = KeywordIndex()


def get_keyword_index() -> KeywordIndex:
    return _keyword_index

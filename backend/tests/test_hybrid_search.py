"""Hybrid retrieval: BM25 keyword search fused with vector similarity.

The motivating failure is concrete. Asking about "Employment at Will"
retrieved the table-of-contents page - which merely lists that heading -
above the section containing the actual policy, because both are topically
similar to the query. Cosine similarity cannot separate them; exact term
matching can.
"""
from langchain_core.documents import Document

from app.rag.keyword_index import KeywordIndex, tokenize
from app.rag.retriever import Retriever


def chunk(text: str, chunk_id: str = "c1", document_id: str = "d1") -> Document:
    return Document(
        page_content=text,
        metadata={"filename": "kb.pdf", "page": 1, "chunk_id": chunk_id, "document_id": document_id},
    )


# ---------------------------------------------------------------------------
# Tokenisation and BM25
# ---------------------------------------------------------------------------


def test_tokenizer_is_case_and_punctuation_insensitive():
    assert tokenize("Employment at Will!") == ["employment", "at", "will"]
    assert tokenize("Section 4.2 - Leave") == ["section", "4", "2", "leave"]


def test_keyword_search_surfaces_exact_term_matches_and_excludes_the_rest():
    """Keyword search contributes *recall* of exact-term matches.

    Note what this does NOT claim: BM25 normalises by document length, so a
    terse table-of-contents line can outscore the section that actually
    contains the policy (measured here: 0.349 vs 0.297). Keyword search
    alone therefore does not fix the contents-page problem either - it
    surfaces both candidates, and fusion with vector search is what decides
    between them. Asserting a specific BM25 winner would encode a
    misunderstanding of what this component is for.
    """
    index = KeywordIndex()
    documents = [
        chunk("Table of contents. Employment at Will .......... 10", "toc"),
        chunk(
            "Employment at Will. Either party may terminate the employment "
            "relationship at any time, with or without cause or notice.",
            "body",
        ),
        chunk("Completely unrelated content about network configuration.", "other"),
    ]
    results = index.search("kb", documents, "employment at will termination", top_k=3)
    returned = {document.metadata["chunk_id"] for document, _ in results}

    # Both term-bearing chunks are candidates...
    assert {"toc", "body"}.issubset(returned)
    # ...and the chunk sharing no query term is excluded outright.
    assert "other" not in returned


def test_keyword_search_returns_nothing_for_unrelated_queries():
    """BM25 scores 0 when no query term appears; those must not pad results."""
    index = KeywordIndex()
    documents = [chunk("Leave policy and holiday entitlement.", "a")]
    assert index.search("kb", documents, "kubernetes ingress controller", top_k=5) == []


def test_keyword_search_handles_empty_corpus_and_query():
    index = KeywordIndex()
    assert index.search("kb", [], "anything", top_k=5) == []
    assert index.search("kb", [chunk("text")], "", top_k=5) == []


def test_index_is_cached_then_invalidated():
    """A stale keyword index would keep serving deleted documents, so
    invalidation must actually drop it."""
    index = KeywordIndex()
    documents = [chunk("leave policy", "a")]

    index.search("kb", documents, "leave", top_k=1)
    assert "kb" in index._entries

    index.invalidate()
    assert index._entries == {}


def test_index_rebuilds_when_the_corpus_size_changes():
    """A newly added document must become searchable without a restart.

    Uses a corpus of several documents deliberately: BM25's IDF term is
    log((N - n + 0.5) / (n + 0.5)), which is exactly 0 when a term appears
    in half the corpus. On a two-document corpus every distinctive term
    would therefore score 0 and the assertion would fail for reasons that
    have nothing to do with cache invalidation.
    """
    index = KeywordIndex()
    original = [chunk(f"unrelated filler text number {i}", f"f{i}") for i in range(5)]
    index.search("kb", original, "filler", top_k=1)

    grown = original + [chunk("annual leave carryover rules apply", "new")]
    results = index.search("kb", grown, "carryover", top_k=3)

    assert results, "a newly indexed document should be findable"
    assert results[0][0].metadata["chunk_id"] == "new"


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def test_fusion_promotes_results_found_by_both_retrievers():
    """Agreement between the two retrievers is the strongest signal, so a
    chunk both find should outrank one that only appears in a single list."""
    shared = chunk("employment at will clause", "shared")
    vector_only = chunk("vaguely related text", "vec")
    keyword_only = chunk("exact phrase match", "kw")

    documents, _, _ = Retriever._fuse(
        vector_results=[(vector_only, 0.4), (shared, 0.3)],
        keyword_results=[(shared, 8.0), (keyword_only, 5.0)],
        top_k=3,
        rrf_k=60,
    )
    assert documents[0].metadata["chunk_id"] == "shared"


def test_fusion_preserves_cosine_scores_for_grading():
    """Context grading is calibrated on the cosine scale, so the returned
    scores must stay cosine - not fused ranks."""
    a = chunk("a", "a")
    b = chunk("b", "b")
    _, scores, _ = Retriever._fuse(
        vector_results=[(a, 0.42)],
        keyword_results=[(b, 12.5)],
        top_k=2,
        rrf_k=60,
    )
    # 0.42 survives; the keyword-only chunk has no cosine score, so 0.0.
    assert sorted(scores) == [0.0, 0.42]
    assert max(scores) == 0.42


def test_fusion_deduplicates_identical_content_from_duplicate_uploads():
    """The same PDF uploaded twice yields identical text under different
    chunk ids; keying on id would let both through and waste half of top_k."""
    first = chunk("identical policy text", chunk_id="doc1_p1_c0", document_id="doc1")
    second = chunk("identical policy text", chunk_id="doc2_p1_c0", document_id="doc2")

    documents, _, _ = Retriever._fuse(
        vector_results=[(first, 0.5), (second, 0.5)],
        keyword_results=[],
        top_k=4,
        rrf_k=60,
    )
    assert len(documents) == 1, "identical content must collapse to one chunk"


def test_fusion_reports_useful_diagnostics():
    documents, _, diagnostics = Retriever._fuse(
        vector_results=[(chunk("a", "a"), 0.3)],
        keyword_results=[(chunk("b", "b"), 4.0)],
        top_k=5,
        rrf_k=60,
    )
    assert diagnostics["vector_hits"] == 1
    assert diagnostics["keyword_hits"] == 1
    assert diagnostics["keyword_only_chunks"] == 1
    assert diagnostics["fused_returned"] == 2


def test_fusion_with_no_keyword_results_is_pure_vector_order():
    """Hybrid must degrade gracefully to vector-only behaviour."""
    high = chunk("high", "high")
    low = chunk("low", "low")
    documents, scores, diagnostics = Retriever._fuse(
        vector_results=[(high, 0.9), (low, 0.1)],
        keyword_results=[],
        top_k=2,
        rrf_k=60,
    )
    assert [d.metadata["chunk_id"] for d in documents] == ["high", "low"]
    assert scores == [0.9, 0.1]
    assert diagnostics["keyword_only_chunks"] == 0

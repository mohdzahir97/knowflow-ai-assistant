"""Mutable state threaded through a RAG pipeline run.

One object carries everything the steps read and write, which is what lets
steps stay independent: a step declares nothing about its neighbours, only
which fields it consumes and produces. That is the property Corrective RAG
depends on - grading, rewriting and re-retrieval can be inserted, reordered
or looped without any step knowing about the others.

Deliberately free of database and HTTP concerns. Session handling and
persistence live in ChatService; keeping them out of here means every step
is testable with a plain object and no fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.schemas.chat import SourceCitation, TokenUsage


@dataclass
class RagContext:
    # --- Inputs: the question and how to answer it -------------------------
    question: str
    user_id: str

    # Which knowledge base to search. Resolved by ChatService before the
    # pipeline runs, because it depends on database state (a document-scoped
    # session must use the embedding config its document was indexed with).
    embedding_provider: str
    embedding_model: str
    embeddings: Embeddings

    # Which chat model to answer with.
    provider: str
    model: str

    # --- Optional tuning ---------------------------------------------------
    document_ids: Optional[List[str]] = None
    top_k: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    # Prior conversation, for resolving follow-up questions. Not a source of
    # facts - see the prompt template.
    history: List[dict] = field(default_factory=list)

    # --- Working state, populated by steps ---------------------------------
    # The query actually sent to retrieval. Starts as `question`; a future
    # rewriting step may replace it while leaving `question` untouched, so
    # the original is always recoverable for logging and citations.
    search_query: str = ""
    chunks: List[Document] = field(default_factory=list)
    answer: Optional[str] = None
    sources: List[SourceCitation] = field(default_factory=list)
    token_usage: Optional[TokenUsage] = None

    # --- Corrective RAG state ---------------------------------------------
    # Relevance score per chunk, index-aligned with `chunks`. Populated by
    # retrieval and consumed by grading, re-ranking and correction.
    chunk_scores: List[float] = field(default_factory=list)
    # "good" | "poor" - whether the retrieved context is worth answering
    # from. Set by the grading step.
    context_verdict: Optional[str] = None
    # Highest relevance score seen; the headline context-quality number.
    context_quality: Optional[float] = None
    # How many corrective retrieval rounds have run, so the loop is bounded.
    correction_attempts: int = 0
    # Every query actually issued, original first, for tracing and debugging.
    attempted_queries: List[str] = field(default_factory=list)
    # Set by groundedness verification when an answer is not supported by
    # the retrieved context.
    groundedness_verdict: Optional[str] = None

    # --- Control flow ------------------------------------------------------
    # A step sets `halted` to stop the run early without raising - used when
    # there is a legitimate final answer that needs no further processing
    # (for example: nothing relevant was retrieved, so respond with the
    # "not found" message rather than calling the model at all).
    halted: bool = False
    halt_reason: Optional[str] = None

    # --- Observability -----------------------------------------------------
    step_timings_ms: Dict[str, float] = field(default_factory=dict)
    # Free-form, non-sensitive annotations steps can leave for tracing and
    # logging (counts, scores, decisions - never document text).
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.search_query:
            self.search_query = self.question

    def halt(self, reason: str) -> None:
        """Stop the pipeline after the current step, without an error."""
        self.halted = True
        self.halt_reason = reason

    def record_timing(self, step_name: str, elapsed_ms: float) -> None:
        # Steps may run more than once (corrective retrieval re-runs
        # retrieval), so accumulate rather than overwrite - otherwise a retry
        # would silently hide the cost of the first attempt.
        self.step_timings_ms[step_name] = round(self.step_timings_ms.get(step_name, 0.0) + elapsed_ms, 2)

    def timing_for(self, step_name: str) -> float:
        return self.step_timings_ms.get(step_name, 0.0)

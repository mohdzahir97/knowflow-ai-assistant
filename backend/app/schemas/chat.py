"""Pydantic schemas for the conversational Q&A endpoints."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SourceCitation(BaseModel):
    document: str
    page: int
    chunk_id: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    provider: str = Field(description="Chat provider to use, e.g. 'openai', 'gemini', 'groq'.")
    model: str = Field(description="Chat model name for the selected provider.")
    embedding_provider: Optional[str] = Field(
        default=None,
        description="Embedding provider the target knowledge base was indexed with. "
        "Required unless 'document_id' is set, in which case the document's own "
        "embedding config is used automatically.",
    )
    embedding_model: Optional[str] = Field(
        default=None, description="Embedding model the target knowledge base was indexed with."
    )
    session_id: Optional[str] = Field(default=None, description="Existing chat session to continue, if any.")
    document_id: Optional[str] = Field(
        default=None,
        description="Scope this conversation to a single document. Reuses the one "
        "existing session for (user, document) if present, else creates it.",
    )
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192)


class TokenUsage(BaseModel):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class CragDiagnostics(BaseModel):
    """What the Corrective RAG pipeline decided, for observability.

    Deliberately free of document text: safe to log, trace and show to an
    administrator without leaking knowledge-base content.
    """

    context_verdict: Optional[str] = None
    context_quality: Optional[float] = None
    correction_attempts: int = 0
    rewritten_query: Optional[str] = None
    groundedness_verdict: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    document_id: Optional[str] = None
    answer: str
    sources: List[SourceCitation]
    provider: str
    model: str
    retrieval_time_ms: float
    llm_time_ms: float
    total_time_ms: float
    token_usage: Optional[TokenUsage] = None
    crag: Optional[CragDiagnostics] = None


class ChatMessageRead(BaseModel):
    id: str
    role: str
    content: str
    sources: Optional[List[SourceCitation]] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionRead(BaseModel):
    id: str
    title: str
    document_id: Optional[str] = None
    created_at: datetime
    messages: List[ChatMessageRead] = []

    model_config = {"from_attributes": True}


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    document_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

"""Conversational RAG pipeline: retrieve -> prompt -> generate -> cite -> persist."""
import time
from typing import AsyncIterator, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AppError,
    AuthorizationError,
    NoDocumentsFoundError,
    ResourceNotFoundError,
    ValidationAppError,
)
from app.core.logging import get_logger, log_extra
from app.core.tracing import traced
from app.db.models.chat import ChatMessage, ChatSession
from app.db.models.document import Document, DocumentStatus
from app.db.models.user import User, UserRole
from app.providers.embeddings import EmbeddingProviderFactory
from app.providers.llm import LLMProviderFactory
from app.rag.pipeline import Pipeline, RagContext, get_rag_pipeline, get_retrieval_pipeline
from app.rag.pipeline.steps.generate import GenerateStep
from app.rag.pipeline.steps.verify import VerifyGroundednessStep
from app.rag.prompt_builder import NO_ANSWER_MESSAGE, PromptBuilder
from app.rag.retriever import Retriever, get_retriever
from app.schemas.chat import ChatRequest, ChatResponse, CragDiagnostics, SourceCitation
from app.services.vector_store_service import VectorStoreService

logger = get_logger("app.chat")

# Number of prior *messages* (not turns) replayed as conversational context.
# One turn = 2 messages (user + assistant), so the default of 6 is 3 turns.
# Previously named _HISTORY_TURNS, which implied twice this much history.
_HISTORY_MESSAGE_LIMIT = 6


class ChatService:
    """Owns the database side of a conversation - sessions, history and
    persistence - and delegates the retrieval/generation work to a pipeline.

    The split matters: the pipeline is pure RAG with no database access, so
    steps are testable in isolation and Corrective RAG's retry loops can
    re-run retrieval freely without touching a transaction.
    """

    def __init__(
        self,
        retriever: Optional[Retriever] = None,
        vector_store: Optional[VectorStoreService] = None,
        pipeline: Optional[Pipeline] = None,
    ) -> None:
        self._retriever = retriever or get_retriever()
        self._vector_store = vector_store or VectorStoreService()
        self._pipeline = pipeline or get_rag_pipeline()
        # Streaming reuses the same retrieval steps, then generates itself.
        self._retrieval_pipeline = get_retrieval_pipeline()
        self._verifier = VerifyGroundednessStep()

    @traced("chat.ask", run_type="chain")
    async def ask(self, db: Session, user: User, request: ChatRequest) -> ChatResponse:
        """Run the retrieval-augmented answer pipeline for one question.

        Async because the two slow steps - embedding the query and calling the
        chat model - are network I/O that can take seconds to minutes. As a
        sync endpoint each request pinned a threadpool worker for its whole
        duration, capping concurrency at the pool size; awaiting them frees
        the event loop to serve other requests meanwhile, and is the
        precondition for streaming responses.

        Database calls remain synchronous: they are sub-millisecond local
        SQLite reads, so the cost of blocking the loop is negligible next to
        the model calls, and keeping them sync avoids an invasive async-ORM
        migration. Revisit if/when the database moves to Postgres.
        """
        total_start = time.perf_counter()
        session, pipeline_context = self._prepare(db, user, request)

        await self._pipeline.run(pipeline_context)

        answer = pipeline_context.answer or NO_ANSWER_MESSAGE
        sources = pipeline_context.sources
        self._persist_turn(db, session, request, answer, sources)

        total_time_ms = round((time.perf_counter() - total_start) * 1000, 2)
        self._log_completion(user, request, pipeline_context, total_time_ms)
        return self._build_response(session, request, pipeline_context, answer, sources, total_time_ms)

    async def ask_stream(self, db: Session, user: User, request: ChatRequest) -> AsyncIterator[dict]:
        """Answer a question, emitting tokens as the model produces them.

        Yields dicts that the route serialises as newline-delimited JSON:
          {"type": "token", "content": ...}   zero or more
          {"type": "done",  ...}              exactly one, on success
          {"type": "error", "message": ...}   instead of "done", on failure

        Retrieval runs to completion first (it has to - the model cannot
        start until it has context), then generation streams. The retrieval
        steps are the same objects the buffered path uses, so the two cannot
        diverge.

        The full turn is persisted only after the stream completes, so an
        abandoned or failed generation never leaves a half-written answer in
        the conversation.
        """
        total_start = time.perf_counter()

        try:
            session, pipeline_context = self._prepare(db, user, request)
            await self._retrieval_pipeline.run(pipeline_context)
        except AppError as exc:
            yield {"type": "error", "message": exc.message}
            return

        # Nothing retrieved: answer with the fixed refusal rather than
        # inviting the model to invent something.
        if not pipeline_context.chunks:
            answer = NO_ANSWER_MESSAGE
            yield {"type": "token", "content": answer}
            self._persist_turn(db, session, request, answer, [])
            yield self._stream_done(session, request, pipeline_context, answer, [], total_start)
            return

        messages = PromptBuilder.build(pipeline_context.chunks, request.question, pipeline_context.history)
        chunks_out: List[str] = []

        try:
            chat_model = LLMProviderFactory.create_chat_model(
                request.provider, request.model, temperature=request.temperature, max_tokens=request.max_tokens
            )
            async for piece in chat_model.astream(messages):
                text = piece.content if isinstance(piece.content, str) else str(piece.content)
                if text:
                    chunks_out.append(text)
                    yield {"type": "token", "content": text}
        except Exception as exc:
            logger.error(
                "Streaming provider call failed",
                extra=log_extra(user_id=user.id, provider=request.provider, error=str(exc)),
            )
            yield {"type": "error", "message": f"The '{request.provider}' provider failed: {exc}"}
            return

        answer = "".join(chunks_out).strip() or NO_ANSWER_MESSAGE
        sources = GenerateStep._build_sources(pipeline_context)
        pipeline_context.answer = answer
        pipeline_context.sources = sources

        # Groundedness verification cannot run before the answer exists, so
        # for streaming it happens after the tokens have been sent. If it
        # rejects the answer, the client is told explicitly rather than the
        # already-displayed text being silently wrong.
        await self._verifier.run(pipeline_context)
        if pipeline_context.groundedness_verdict == "ungrounded":
            answer = pipeline_context.answer
            sources = []
            yield {"type": "retract", "content": answer}

        self._persist_turn(db, session, request, answer, sources)
        yield self._stream_done(session, request, pipeline_context, answer, sources, total_start)

    def _stream_done(self, session, request, pipeline_context, answer, sources, total_start) -> dict:
        total_time_ms = round((time.perf_counter() - total_start) * 1000, 2)
        response = self._build_response(session, request, pipeline_context, answer, sources, total_time_ms)
        return {"type": "done", **response.model_dump(mode="json")}

    def _prepare(self, db: Session, user: User, request: ChatRequest) -> tuple[ChatSession, RagContext]:
        """Resolve the session, history and knowledge base for a question.

        Shared by the buffered and streaming paths: both need identical
        session handling, authorization and knowledge-base resolution, and
        duplicating that would be the obvious place for the two to drift
        apart.
        """
        session = self._get_or_create_session(db, user, request)
        history = self._load_history(db, session)

        if session.document_id:
            # Document-scoped chat: always search only this document, using the
            # exact embedding config it was indexed with — the request's own
            # embedding_provider/model (if any) are ignored, since the wrong
            # config would simply search the wrong (or an empty) collection.
            document = db.get(Document, session.document_id)
            embedding_provider = document.embedding_provider
            embedding_model = document.embedding_model
            document_ids_filter: Optional[List[str]] = [session.document_id]
        else:
            if not request.embedding_provider or not request.embedding_model:
                raise ValidationAppError(
                    "embedding_provider and embedding_model are required unless document_id is set."
                )
            embedding_provider = request.embedding_provider
            embedding_model = request.embedding_model
            document_ids_filter = None

            # Is there anything in the shared knowledge base for this
            # embedding configuration? Answered from the SQL system of record
            # rather than by scanning ChromaDB metadata.
            #
            # Not filtered by user: the knowledge base is shared, curated by
            # admins, and every end user queries the same corpus.
            has_indexed_document = db.scalar(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.status == DocumentStatus.INDEXED,
                    Document.embedding_provider == embedding_provider,
                    Document.embedding_model == embedding_model,
                )
                .limit(1)
            )
            if not has_indexed_document:
                # Phrased for an end user, who knows nothing about documents,
                # embeddings or indexing - only that the assistant currently
                # has nothing to answer from.
                raise NoDocumentsFoundError(
                    "The knowledge base is empty, so there is nothing to answer from yet. "
                    "Please contact an administrator."
                )

        embeddings = EmbeddingProviderFactory.create_embeddings(embedding_provider, embedding_model)

        # Hand off to the pipeline. Everything from here to the response is
        # composed of steps, so Corrective RAG and guardrails are added by
        # extending the pipeline rather than by editing this method.
        pipeline_context = RagContext(
            question=request.question,
            user_id=user.id,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embeddings=embeddings,
            provider=request.provider,
            model=request.model,
            document_ids=document_ids_filter,
            top_k=request.top_k,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            history=history,
        )
        return session, pipeline_context

    @staticmethod
    def _log_completion(user, request, pipeline_context, total_time_ms) -> None:
        logger.info(
            "Chat request completed",
            extra=log_extra(
                user_id=user.id,
                provider=request.provider,
                model=request.model,
                total_time_ms=total_time_ms,
                step_timings_ms=pipeline_context.step_timings_ms,
                halt_reason=pipeline_context.halt_reason,
                context_verdict=pipeline_context.context_verdict,
                context_quality=pipeline_context.context_quality,
                correction_attempts=pipeline_context.correction_attempts,
            ),
        )

    @staticmethod
    def _build_response(session, request, pipeline_context, answer, sources, total_time_ms) -> ChatResponse:
        return ChatResponse(
            session_id=session.id,
            document_id=session.document_id,
            answer=answer,
            sources=sources,
            provider=request.provider,
            model=request.model,
            # Timings come from the pipeline's per-step accounting. Named
            # after the steps that produce them so the response contract is
            # unchanged even as more steps are added around them.
            retrieval_time_ms=pipeline_context.timing_for("retrieve"),
            llm_time_ms=pipeline_context.timing_for("generate"),
            total_time_ms=total_time_ms,
            token_usage=pipeline_context.token_usage,
            crag=CragDiagnostics(
                context_verdict=pipeline_context.context_verdict,
                context_quality=pipeline_context.context_quality,
                correction_attempts=pipeline_context.correction_attempts,
                # Only meaningful if a rewrite actually happened.
                rewritten_query=(
                    pipeline_context.attempted_queries[-1]
                    if pipeline_context.correction_attempts and len(pipeline_context.attempted_queries) > 1
                    else None
                ),
                groundedness_verdict=pipeline_context.groundedness_verdict,
            ),
        )

    def _get_or_create_session(self, db: Session, user: User, request: ChatRequest) -> ChatSession:
        if request.session_id:
            session = db.get(ChatSession, request.session_id)
            if not session or session.user_id != user.id:
                raise ResourceNotFoundError("Chat session not found.")
            return session

        if request.document_id:
            # Scoping a conversation to one document is an ADMIN capability:
            # it exists so an admin can verify that a freshly uploaded
            # document is indexed and retrievable. End users must never
            # choose - or even learn of - the documents behind an answer, so
            # this is refused for them rather than silently ignored.
            if user.role != UserRole.ADMIN:
                raise AuthorizationError("Selecting a specific document requires administrator privileges.")

            # No ownership check: the knowledge base is shared, so any admin
            # may test any document in it.
            document = db.get(Document, request.document_id)
            if not document:
                raise ResourceNotFoundError("Document not found.")

            existing = db.scalar(
                select(ChatSession).where(
                    ChatSession.user_id == user.id, ChatSession.document_id == request.document_id
                )
            )
            if existing:
                return existing

            session = ChatSession(user_id=user.id, document_id=document.id, title=document.filename)
            db.add(session)
            try:
                db.commit()
            except IntegrityError:
                # A concurrent request created this document's session between
                # our SELECT above and this INSERT. The unique constraint is
                # the authority; fall back to whichever row won the race so
                # both requests converge on one conversation.
                db.rollback()
                existing = db.scalar(
                    select(ChatSession).where(
                        ChatSession.user_id == user.id, ChatSession.document_id == request.document_id
                    )
                )
                if existing is None:
                    raise
                return existing
            db.refresh(session)
            return session

        title = (request.question[:60] + "...") if len(request.question) > 60 else request.question
        session = ChatSession(user_id=user.id, title=title)
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def _load_history(self, db: Session, session: ChatSession) -> List[dict]:
        messages = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(_HISTORY_MESSAGE_LIMIT)
        ).all()
        return [{"role": m.role, "content": m.content} for m in reversed(list(messages))]

    # Citation building and token-usage extraction now live in GenerateStep,
    # alongside the model call that produces them.

    def _persist_turn(self, db: Session, session: ChatSession, request: ChatRequest, answer: str, sources: List[SourceCitation]) -> None:
        db.add(ChatMessage(session_id=session.id, role="user", content=request.question))
        db.add(
            ChatMessage(
                session_id=session.id,
                role="assistant",
                content=answer,
                sources=[s.model_dump() for s in sources],
                provider=request.provider,
                model=request.model,
            )
        )
        db.commit()

    def list_sessions(self, db: Session, user: User) -> List[ChatSession]:
        return list(
            db.scalars(select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.created_at.desc()))
        )

    def get_session(self, db: Session, user: User, session_id: str) -> ChatSession:
        session = db.get(ChatSession, session_id)
        if not session or session.user_id != user.id:
            raise ResourceNotFoundError("Chat session not found.")
        return session

    def delete_session(self, db: Session, user: User, session_id: str) -> None:
        session = self.get_session(db, user, session_id)
        db.delete(session)
        db.commit()

    def get_document_chat(self, db: Session, user: User, document_id: str) -> Optional[ChatSession]:
        """Return the single chat session scoped to this document, or None if
        no conversation has happened for it yet."""
        return db.scalar(
            select(ChatSession).where(ChatSession.user_id == user.id, ChatSession.document_id == document_id)
        )

    def clear_document_chat(self, db: Session, user: User, document_id: str) -> None:
        """Delete all chat history for a document. Idempotent — succeeds even
        if no conversation exists yet, so callers don't need to check first."""
        session = self.get_document_chat(db, user, document_id)
        if session:
            db.delete(session)
            db.commit()

    def delete_message(self, db: Session, user: User, message_id: str) -> None:
        message = db.get(ChatMessage, message_id)
        if not message:
            raise ResourceNotFoundError("Chat message not found.")
        session = db.get(ChatSession, message.session_id)
        if not session or session.user_id != user.id:
            raise ResourceNotFoundError("Chat message not found.")
        db.delete(message)
        db.commit()


def get_chat_service() -> ChatService:
    return ChatService()

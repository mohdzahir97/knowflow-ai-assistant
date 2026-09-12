"""Conversational Q&A endpoints — RAG pipeline + session history, scoped per user."""
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentAdmin, CurrentUser, DbSession
from app.api.rate_limit_deps import rate_limit_chat
from app.schemas.chat import ChatRequest, ChatResponse, ChatSessionRead, ChatSessionSummary
from app.schemas.common import APIResponse
from app.services.chat_service import get_chat_service

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/ask", response_model=APIResponse[ChatResponse], dependencies=[Depends(rate_limit_chat)])
async def ask(payload: ChatRequest, request: Request, db: DbSession, user: CurrentUser) -> APIResponse[ChatResponse]:
    """Async so the LLM/embedding round trips don't pin a threadpool worker
    for the lifetime of the request. The remaining routes stay synchronous:
    they only do fast local database work, and FastAPI runs sync handlers in
    its threadpool, which is the right place for short blocking calls."""
    service = get_chat_service()
    result = await service.ask(db, user, payload)
    return APIResponse.ok(request_id=request.state.request_id, message="Answer generated.", data=result)


@router.post("/ask/stream", dependencies=[Depends(rate_limit_chat)])
async def ask_stream(payload: ChatRequest, request: Request, db: DbSession, user: CurrentUser) -> StreamingResponse:
    """Answer a question as a stream of newline-delimited JSON events.

    NDJSON rather than Server-Sent Events: each line is a complete JSON
    object, which any HTTP client can parse with a readline loop and no SSE
    library. Event shapes are documented on `ChatService.ask_stream`.

    Errors are delivered as an in-stream `error` event rather than an HTTP
    status, because the response has already begun by the time generation
    can fail - the status line is long gone.
    """
    service = get_chat_service()

    async def event_stream():
        async for event in service.ask_stream(db, user, payload):
            yield json.dumps(event) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            # Stop reverse proxies buffering the response, which would
            # defeat streaming by delivering everything at the end.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request.state.request_id,
        },
    )


@router.get("/sessions", response_model=APIResponse[List[ChatSessionSummary]])
def list_sessions(request: Request, db: DbSession, user: CurrentUser) -> APIResponse[List[ChatSessionSummary]]:
    service = get_chat_service()
    sessions = service.list_sessions(db, user)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Sessions retrieved.",
        data=[ChatSessionSummary.model_validate(s) for s in sessions],
    )


@router.get("/sessions/{session_id}", response_model=APIResponse[ChatSessionRead])
def get_session(session_id: str, request: Request, db: DbSession, user: CurrentUser) -> APIResponse[ChatSessionRead]:
    service = get_chat_service()
    session = service.get_session(db, user, session_id)
    return APIResponse.ok(
        request_id=request.state.request_id, message="Session retrieved.", data=ChatSessionRead.model_validate(session)
    )


@router.delete("/sessions/{session_id}", response_model=APIResponse[None])
def delete_session(session_id: str, request: Request, db: DbSession, user: CurrentUser) -> APIResponse[None]:
    service = get_chat_service()
    service.delete_session(db, user, session_id)
    return APIResponse.ok(request_id=request.state.request_id, message="Session deleted.")


@router.get("/documents/{document_id}", response_model=APIResponse[Optional[ChatSessionRead]])
def get_document_chat(document_id: str, request: Request, db: DbSession, user: CurrentAdmin) -> APIResponse[Optional[ChatSessionRead]]:
    """Admin-only. This document's testing conversation, or `data: null` if
    none has happened yet. End users never address documents directly."""
    service = get_chat_service()
    session = service.get_document_chat(db, user, document_id)
    data = ChatSessionRead.model_validate(session) if session else None
    return APIResponse.ok(request_id=request.state.request_id, message="Document chat history retrieved.", data=data)


@router.delete("/documents/{document_id}", response_model=APIResponse[None])
def clear_document_chat(document_id: str, request: Request, db: DbSession, user: CurrentAdmin) -> APIResponse[None]:
    """Admin-only. Clears a document's testing conversation. Idempotent."""
    service = get_chat_service()
    service.clear_document_chat(db, user, document_id)
    return APIResponse.ok(request_id=request.state.request_id, message="Document chat history cleared.")


@router.delete("/messages/{message_id}", response_model=APIResponse[None])
def delete_message(message_id: str, request: Request, db: DbSession, user: CurrentUser) -> APIResponse[None]:
    service = get_chat_service()
    service.delete_message(db, user, message_id)
    return APIResponse.ok(request_id=request.state.request_id, message="Message deleted.")

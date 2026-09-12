"""Project and chat-organisation endpoints.

Every route is scoped to the signed-in user by the service layer. There is
deliberately no way to address another user's project or chat: an id that
belongs to someone else returns 404, identical to one that does not exist,
so responses cannot be used to probe for valid ids.
"""
from typing import List, Optional

from fastapi import APIRouter, Query, Request, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import APIResponse
from app.schemas.project import (
    ChatMoveRequest,
    ChatRename,
    ChatSummary,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)
from app.services.project_service import get_project_service

router = APIRouter(tags=["Projects & Chats"])


def _to_summary(chat, message_count: int) -> ChatSummary:
    return ChatSummary(
        id=chat.id,
        title=chat.title,
        project_id=chat.project_id,
        document_id=chat.document_id,
        message_count=message_count,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.post("/projects", response_model=APIResponse[ProjectRead], status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request, db: DbSession, user: CurrentUser):
    project = get_project_service().create(db, user, payload.name)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Project created.",
        data=ProjectRead(id=project.id, name=project.name, chat_count=0, created_at=project.created_at),
    )


@router.get("/projects", response_model=APIResponse[List[ProjectRead]])
def list_projects(request: Request, db: DbSession, user: CurrentUser):
    rows = get_project_service().list_projects(db, user)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Projects retrieved.",
        data=[
            ProjectRead(id=p.id, name=p.name, chat_count=count, created_at=p.created_at) for p, count in rows
        ],
    )


@router.patch("/projects/{project_id}", response_model=APIResponse[ProjectRead])
def rename_project(project_id: str, payload: ProjectUpdate, request: Request, db: DbSession, user: CurrentUser):
    project = get_project_service().rename(db, user, project_id, payload.name)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Project renamed.",
        data=ProjectRead(id=project.id, name=project.name, created_at=project.created_at),
    )


@router.delete("/projects/{project_id}", response_model=APIResponse[None])
def delete_project(project_id: str, request: Request, db: DbSession, user: CurrentUser):
    """Deletes the project only. Its chats are detached, never deleted."""
    detached = get_project_service().delete(db, user, project_id)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message=f"Project deleted. {detached} chat(s) moved out of it.",
    )


@router.get("/projects/{project_id}/chats", response_model=APIResponse[List[ChatSummary]])
def list_project_chats(project_id: str, request: Request, db: DbSession, user: CurrentUser):
    rows = get_project_service().list_chats(db, user, project_id=project_id)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Chats retrieved.",
        data=[_to_summary(chat, count) for chat, count in rows],
    )


# ---------------------------------------------------------------------------
# Chat organisation
# ---------------------------------------------------------------------------


@router.get("/chats", response_model=APIResponse[List[ChatSummary]])
def list_chats(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    ungrouped_only: bool = Query(False, description="Only chats not in any project."),
    search: Optional[str] = Query(None, description="Search titles and message content."),
):
    """Chat history. Optionally filtered to ungrouped chats, or searched."""
    service = get_project_service()
    if search:
        rows = service.search_chats(db, user, search)
    else:
        rows = service.list_chats(db, user, ungrouped_only=ungrouped_only)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Chats retrieved.",
        data=[_to_summary(chat, count) for chat, count in rows],
    )


@router.patch("/chats/{chat_id}", response_model=APIResponse[ChatSummary])
def rename_chat(chat_id: str, payload: ChatRename, request: Request, db: DbSession, user: CurrentUser):
    chat = get_project_service().rename_chat(db, user, chat_id, payload.title)
    return APIResponse.ok(
        request_id=request.state.request_id, message="Chat renamed.", data=_to_summary(chat, 0)
    )


@router.patch("/chats/{chat_id}/project", response_model=APIResponse[ChatSummary])
def move_chat(chat_id: str, payload: ChatMoveRequest, request: Request, db: DbSession, user: CurrentUser):
    """Move a chat into a project, or out of one by passing a null project_id."""
    chat = get_project_service().move_chat(db, user, chat_id, payload.project_id)
    message = "Chat moved into project." if payload.project_id else "Chat removed from project."
    return APIResponse.ok(request_id=request.state.request_id, message=message, data=_to_summary(chat, 0))

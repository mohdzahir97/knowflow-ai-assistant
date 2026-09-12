"""Pydantic schemas for projects and chat organisation."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_and_require_content(cls, value: str) -> str:
        # A name of only whitespace passes min_length but renders as blank.
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Project name cannot be blank.")
        return cleaned


class ProjectUpdate(ProjectCreate):
    """Renaming takes the same shape and validation as creating."""


class ProjectRead(BaseModel):
    id: str
    name: str
    chat_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def strip_and_require_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Chat title cannot be blank.")
        return cleaned


class ChatMoveRequest(BaseModel):
    # Null moves the chat out of any project, back to the ungrouped list.
    project_id: Optional[str] = None


class ChatSummary(BaseModel):
    """A chat as it appears in history lists and project listings."""

    id: str
    title: str
    project_id: Optional[str] = None
    document_id: Optional[str] = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSearchResult(BaseModel):
    chats: List[ChatSummary] = []
    query: str

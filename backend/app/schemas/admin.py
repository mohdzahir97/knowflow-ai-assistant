"""Schemas for the administrator observability endpoints."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class AuditEventRead(BaseModel):
    id: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    request_id: Optional[str] = None
    detail: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProviderModelRead(BaseModel):
    id: str
    kind: str
    provider: str
    model_name: str
    display_name: Optional[str] = None
    is_enabled: bool
    sort_order: int

    model_config = {"from_attributes": True}


class ProviderModelCreate(BaseModel):
    kind: Literal["chat", "embedding"]
    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=200)
    display_name: Optional[str] = Field(default=None, max_length=200)
    sort_order: int = 0


class ProviderModelUpdate(BaseModel):
    """Every field optional - a PATCH that omits a field leaves it alone."""

    display_name: Optional[str] = Field(default=None, max_length=200)
    is_enabled: Optional[bool] = None
    sort_order: Optional[int] = None


class Metrics(BaseModel):
    """Operational counts, deliberately cheap to produce.

    Every figure is a SQL aggregate, so this stays fast as the tables grow
    and never loads rows into memory to count them.
    """

    users_total: int
    users_admin: int
    documents_total: int
    document_chunks_total: int
    chat_sessions_total: int
    chat_messages_total: int
    projects_total: int
    audit_events_total: int
    logins_failed_last_24h: int

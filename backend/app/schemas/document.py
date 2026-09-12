"""Pydantic schemas for document upload/listing."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.db.models.document import DocumentStatus


class DocumentRead(BaseModel):
    id: str
    filename: str
    status: DocumentStatus
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    file_size_bytes: int
    failure_reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

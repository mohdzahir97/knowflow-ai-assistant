"""Shared response envelope used by every API endpoint."""
from datetime import datetime, timezone
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    success: bool
    message: str
    data: Optional[T] = None
    errors: Optional[List[str]] = None
    request_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def ok(
        cls,
        request_id: str,
        message: str = "Success",
        data: Optional[T] = None,
        errors: Optional[List[str]] = None,
    ) -> "APIResponse[T]":
        return cls(success=True, message=message, data=data, errors=errors, request_id=request_id)

    @classmethod
    def fail(
        cls,
        request_id: str,
        message: str = "Request failed",
        errors: Optional[List[str]] = None,
    ) -> "APIResponse[Any]":
        return cls(success=False, message=message, data=None, errors=errors or [], request_id=request_id)

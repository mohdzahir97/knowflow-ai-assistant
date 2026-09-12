"""Schemas describing available chat/embedding providers and their models."""
from typing import List

from pydantic import BaseModel


class ProviderInfo(BaseModel):
    provider: str
    display_name: str
    models: List[str]
    is_configured: bool

"""Endpoints exposing available chat/embedding providers and their models.

The frontend must fetch this dynamically rather than hardcoding provider
or model names — new providers become visible the moment they're
registered in `app.providers.llm` / `app.providers.embeddings`.
"""
from typing import List

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser
from app.providers.embeddings import EmbeddingProviderFactory
from app.providers.llm import LLMProviderFactory
from app.schemas.common import APIResponse
from app.schemas.provider import ProviderInfo

router = APIRouter(prefix="/providers", tags=["Providers"])


@router.get("/chat", response_model=APIResponse[List[ProviderInfo]])
def list_chat_providers(request: Request, _: CurrentUser) -> APIResponse[List[ProviderInfo]]:
    providers = [ProviderInfo(**p.to_metadata()) for p in LLMProviderFactory.list_providers()]
    return APIResponse.ok(request_id=request.state.request_id, message="Chat providers retrieved.", data=providers)


@router.get("/embeddings", response_model=APIResponse[List[ProviderInfo]])
def list_embedding_providers(request: Request, _: CurrentUser) -> APIResponse[List[ProviderInfo]]:
    providers = [ProviderInfo(**p.to_metadata()) for p in EmbeddingProviderFactory.list_providers()]
    return APIResponse.ok(
        request_id=request.state.request_id, message="Embedding providers retrieved.", data=providers
    )

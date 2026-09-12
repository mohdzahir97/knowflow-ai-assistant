"""Unauthenticated health check — mounted at the application root, not under /api/v1."""
import chromadb
from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.providers.embeddings import EmbeddingProviderFactory
from app.providers.llm import LLMProviderFactory
from app.schemas.common import APIResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=APIResponse[dict])
def health_check(request: Request) -> APIResponse[dict]:
    settings = get_settings()

    try:
        client = chromadb.PersistentClient(path=str(settings.chroma_path))
        client.heartbeat()
        chromadb_status = "ok"
    except Exception:
        chromadb_status = "unavailable"

    data = {
        "api_status": "ok",
        "version": settings.app_version,
        "chromadb_status": chromadb_status,
        "chat_providers": [p.name for p in LLMProviderFactory.list_providers() if p.is_configured()],
        "embedding_providers": [p.name for p in EmbeddingProviderFactory.list_providers() if p.is_configured()],
    }
    return APIResponse.ok(request_id=request.state.request_id, message="Service is healthy.", data=data)

"""FastAPI application entrypoint (app factory)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import MaxBodySizeMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.providers.embeddings import EmbeddingProviderFactory
from app.providers.llm import LLMProviderFactory

settings = get_settings()
configure_logging()
logger = get_logger("app.main")

_OPENAPI_TAGS = [
    {"name": "Health", "description": "Unauthenticated liveness/readiness check."},
    {"name": "Authentication", "description": "Local registration, login, token refresh, and logout."},
    {"name": "Providers", "description": "Available chat/embedding providers and models, fetched dynamically."},
    {"name": "Documents", "description": "PDF upload, listing, deletion, and knowledge-base management."},
    {"name": "Chat", "description": "Retrieval-augmented question answering and conversation history."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configured_chat = [p.name for p in LLMProviderFactory.list_providers() if p.is_configured()]
    configured_embeddings = [p.name for p in EmbeddingProviderFactory.list_providers() if p.is_configured()]
    logger.info(f"Starting {settings.app_name} v{settings.app_version} [{settings.environment}]")
    logger.info(f"Configured chat providers: {configured_chat or 'none'}")
    logger.info(f"Configured embedding providers: {configured_embeddings or 'none'}")

    # Initialise tracing eagerly so any misconfiguration is reported at
    # startup rather than on the first user question.
    from app.core.tracing import get_tracing_client

    if get_tracing_client() is None:
        logger.info("LangSmith tracing: disabled")

    # Housekeeping: drop revocation records for tokens that have already
    # expired. Cheap, and keeps the table from growing without bound. A
    # failure here must never prevent the application from starting.
    try:
        from app.db.session import SessionLocal
        from app.services.auth_service import get_auth_service

        with SessionLocal() as db:
            get_auth_service().prune_expired_tokens(db)
    except Exception:
        logger.exception("Startup token pruning failed; continuing")

    yield
    logger.info(f"Shutting down {settings.app_name}")


def create_app() -> FastAPI:
    is_production = settings.environment.lower() == "production"

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        openapi_tags=_OPENAPI_TAGS,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(MaxBodySizeMiddleware)
    # Added last so it wraps everything above: hardening headers must reach
    # error and rejection responses too, not only successful handlers.
    app.add_middleware(SecurityHeadersMiddleware)

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()

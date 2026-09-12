"""LangSmith tracing with content redaction.

LangSmith is a hosted service, so every traced run leaves this machine. The
documents indexed here are private company material, so by default this
module sends only the *shape* of a run - step names, timings, token counts,
providers, models, counts and scores - and replaces free text (questions,
retrieved chunks, generated answers) with a redaction marker plus a length,
which is enough to debug retrieval behaviour without exfiltrating content.

Set LANGSMITH_REDACT_CONTENT=false to send full payloads (useful in local
development against non-sensitive fixtures).

Everything here degrades to a no-op when tracing is disabled or no API key
is configured, so application code can be annotated unconditionally.
"""
from __future__ import annotations

import functools
from typing import Any, Callable, Dict, Optional, TypeVar

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("app.tracing")

F = TypeVar("F", bound=Callable[..., Any])

# Keys whose values are free text derived from user data and must never be
# transmitted verbatim when redaction is on.
_SENSITIVE_KEYS = {
    "question",
    "query",
    "answer",
    "content",
    "page_content",
    "text",
    "context",
    "chunks",
    "documents",
    "history",
    "messages",
    "input",
    "output",
    "prompt",
}

_REDACTED = "<redacted>"


def _redact_value(key: str, value: Any) -> Any:
    """Replace sensitive values with a marker that preserves useful shape."""
    if key.lower() not in _SENSITIVE_KEYS:
        return value
    if isinstance(value, str):
        return f"{_REDACTED} (len={len(value)})"
    if isinstance(value, (list, tuple)):
        return f"{_REDACTED} ({len(value)} items)"
    if isinstance(value, dict):
        return f"{_REDACTED} ({len(value)} keys)"
    return _REDACTED


def _redact(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"value": _REDACTED}
    return {key: _redact_value(key, value) for key, value in payload.items()}


_client_initialised = False
_client: Optional[Any] = None


def get_tracing_client() -> Optional[Any]:
    """Return a configured LangSmith client, or None when tracing is off.

    Cached manually rather than with lru_cache so tests can reset it via
    `reset_tracing()` after changing settings.
    """
    global _client_initialised, _client
    if _client_initialised:
        return _client

    _client_initialised = True
    settings = get_settings()

    if not settings.langsmith_tracing:
        _client = None
        return _client

    if not settings.langsmith_api_key:
        # Misconfiguration should degrade to "no tracing", never to a crash
        # or - worse - to sending data somewhere unauthenticated.
        logger.warning("LANGSMITH_TRACING is enabled but no API key is set; tracing disabled.")
        _client = None
        return _client

    try:
        from langsmith import Client

        redact = settings.langsmith_redact_content
        _client = Client(
            api_key=settings.langsmith_api_key,
            api_url=settings.langsmith_endpoint,
            hide_inputs=_redact if redact else False,
            hide_outputs=_redact if redact else False,
        )
        logger.info(
            "LangSmith tracing enabled",
            extra={"extra_fields": {"project": settings.langsmith_project, "redact_content": redact}},
        )
    except Exception:
        logger.exception("Failed to initialise LangSmith client; continuing without tracing")
        _client = None

    return _client


def reset_tracing() -> None:
    """Drop the cached client so the next call re-reads settings (tests)."""
    global _client_initialised, _client
    _client_initialised = False
    _client = None


def traced(name: str, run_type: str = "chain") -> Callable[[F], F]:
    """Decorate a function so its execution appears as a LangSmith span.

    A no-op when tracing is disabled, so call sites need no conditionals.
    The wrapped callable is built once on first traced call and reused.
    """

    def decorator(func: F) -> F:
        wrapped_holder: Dict[str, Any] = {}

        def _get_wrapped(client: Any) -> Callable[..., Any]:
            if "fn" not in wrapped_holder:
                from langsmith import traceable

                wrapped_holder["fn"] = traceable(
                    name=name,
                    run_type=run_type,
                    client=client,
                    project_name=get_settings().langsmith_project,
                )(func)
            return wrapped_holder["fn"]

        if _is_async(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                client = get_tracing_client()
                if client is None:
                    return await func(*args, **kwargs)
                try:
                    return await _get_wrapped(client)(*args, **kwargs)
                except Exception:
                    raise

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            client = get_tracing_client()
            if client is None:
                return func(*args, **kwargs)
            return _get_wrapped(client)(*args, **kwargs)

        return sync_wrapper  # type: ignore[return-value]

    return decorator


def _is_async(func: Callable[..., Any]) -> bool:
    import inspect

    return inspect.iscoroutinefunction(func)

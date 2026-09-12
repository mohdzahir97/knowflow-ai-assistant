"""FastAPI dependencies that apply rate limits to specific routes.

Applied per route rather than globally, because the right limit differs by
what the route costs: an LLM call is expensive and slow, a login attempt is
cheap but security-sensitive, and listing chats is neither.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.exceptions import RateLimitError
from app.core.logging import get_logger, log_extra
from app.core.rate_limit import RateLimitRule, get_rate_limiter
from app.core.security import decode_token

logger = get_logger("app.rate_limit")

# Optional bearer so an unauthenticated request is limited by IP rather than
# rejected here - authentication itself is enforced by the route's own
# dependencies.
_optional_bearer = HTTPBearer(auto_error=False)


def _identity(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    """Prefer the user id; fall back to client IP.

    Limiting authenticated traffic by user rather than address matters: many
    users can share one NAT address, and one heavy user should not be able
    to exhaust everyone else's allowance.
    """
    if credentials is not None:
        try:
            payload = decode_token(credentials.credentials)
            return f"user:{payload['sub']}"
        except Exception:
            # An invalid token is not an identity; fall through to IP so a
            # broken token cannot be used to dodge limits.
            pass
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


def _enforce(request: Request, credentials, rule: RateLimitRule, scope: str) -> None:
    if not get_settings().rate_limit_enabled:
        return

    key = f"{scope}:{_identity(request, credentials)}"
    allowed, retry_after = get_rate_limiter().check(key, rule)
    if allowed:
        return

    logger.warning(
        "Rate limit exceeded",
        extra=log_extra(scope=scope, rule=rule.describe(), retry_after_seconds=retry_after, path=request.url.path),
    )
    raise RateLimitError(
        f"Too many requests. Limit is {rule.describe()}. Try again in {retry_after}s."
    )


def rate_limit_chat(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
) -> None:
    """Guards the expensive path: every question is at least one model call."""
    settings = get_settings()
    _enforce(
        request,
        credentials,
        RateLimitRule(settings.rate_limit_chat_per_minute, 60),
        scope="chat",
    )


def rate_limit_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
) -> None:
    """Guards login/register against credential brute-forcing."""
    settings = get_settings()
    _enforce(
        request,
        credentials,
        RateLimitRule(settings.rate_limit_auth_per_minute, 60),
        scope="auth",
    )


def rate_limit_upload(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
) -> None:
    """Guards indexing, which is the most resource-intensive operation."""
    settings = get_settings()
    _enforce(
        request,
        credentials,
        RateLimitRule(settings.rate_limit_upload_per_hour, 3600),
        scope="upload",
    )

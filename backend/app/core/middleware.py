"""HTTP middleware: security headers, request size limiting, request ID
propagation, and request/response logging."""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.logging import get_logger, log_extra, set_request_id
from app.schemas.common import APIResponse

logger = get_logger("app.request")


# The API returns JSON and nothing else: it never needs to load a script,
# style, image or frame, so the policy denies every source by default.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

# Swagger UI and ReDoc are real HTML pages that load their assets from a CDN,
# so the API's own "load nothing" policy would blank them. They are disabled
# entirely when ENVIRONMENT=production.
_DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})
_DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' https://fastapi.tiangolo.com data:; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds hardening headers to every response.

    Registered outermost so it also covers responses produced by the other
    middleware (such as a 413 for an oversized body) and error responses,
    not just successful route handlers.

    No CSRF token is issued, deliberately: this API authenticates with a
    Bearer token that the client attaches explicitly, and sets no cookies.
    A cross-site request therefore carries no ambient credentials to abuse,
    which is the condition CSRF tokens exist to address. Adding them here
    would be ceremony, not protection. That reasoning stops holding the
    moment any endpoint starts authenticating from a cookie.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        settings = get_settings()
        if not settings.security_headers_enabled:
            return response

        response.headers["Content-Security-Policy"] = (
            _DOCS_CSP if request.url.path in _DOCS_PATHS else _API_CSP
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), interest-cohort=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"

        # Only over HTTPS. Sent on a plain-HTTP response it is ignored by
        # browsers anyway, and asserting it from a local dev server invites
        # pinning a hostname to HTTPS before there is a certificate for it.
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        if request.url.scheme == "https" or forwarded_proto == "https":
            response.headers["Strict-Transport-Security"] = (
                f"max-age={settings.hsts_max_age_seconds}; includeSubDomains"
            )

        # The server banner names the stack and version to anyone scanning.
        response.headers["Server"] = settings.app_name
        return response


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Rejects oversized requests using the Content-Length header alone,
    before multipart/JSON parsing begins — a defense the ASGI stack does
    not provide out of the box.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        max_bytes = get_settings().max_request_body_mb * 1024 * 1024
        if content_length is not None and int(content_length) > max_bytes:
            request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
            logger.warning(
                "Request rejected: body too large",
                extra=log_extra(path=request.url.path, content_length=content_length, max_bytes=max_bytes),
            )
            response = APIResponse.fail(
                request_id=request_id,
                message="Request body exceeds the maximum allowed size.",
                errors=["Request body exceeds the maximum allowed size."],
            )
            return JSONResponse(status_code=413, content=response.model_dump(mode="json"))
        return await call_next(request)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a unique request ID to every inbound request and logs
    the request/response lifecycle including total processing time.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        set_request_id(request_id)
        request.state.request_id = request_id

        start_time = time.perf_counter()
        logger.info(
            "Incoming request",
            extra=log_extra(method=request.method, path=request.url.path, client=request.client.host if request.client else None),
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "Unhandled exception while processing request",
                extra=log_extra(method=request.method, path=request.url.path, duration_ms=duration_ms),
            )
            raise

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "Request completed",
            extra=log_extra(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            ),
        )
        return response

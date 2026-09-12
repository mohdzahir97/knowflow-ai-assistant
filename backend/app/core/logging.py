"""Production-grade structured logging configuration.

Provides console + rotating-file handlers, a JSON formatter, and a
contextvar-backed request ID that is automatically injected into every
log record emitted during a request's lifecycle.
"""
import json
import logging
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from typing import Any, Dict

from app.core.config import get_settings

_REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE_KEYS = {"api_key", "apikey", "password", "secret", "token", "authorization"}


def set_request_id(request_id: str) -> None:
    _REQUEST_ID_CTX.set(request_id)


def get_request_id() -> str:
    return _REQUEST_ID_CTX.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class RedactingJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON, redacting sensitive fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }

        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(self._redact(extra))

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)

    def _redact(self, data: Dict[str, Any]) -> Dict[str, Any]:
        redacted = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in _SENSITIVE_KEYS):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = value
        return redacted


def configure_logging() -> None:
    """Configure root logging handlers. Call once at application startup."""
    settings = get_settings()
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level.upper())

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    formatter = RedactingJsonFormatter()
    request_filter = RequestIdFilter()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(request_filter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        filename=settings.log_path / "app.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(request_filter)
    root_logger.addHandler(file_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_extra(**fields: Any) -> Dict[str, Any]:
    """Helper to attach structured fields to a log call via `extra`."""
    return {"extra_fields": fields}

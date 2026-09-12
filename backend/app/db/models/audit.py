"""Audit log - an append-only record of security-relevant actions.

Scope is deliberately narrow: authentication outcomes, role changes, and
changes to the shared knowledge base. Ordinary reads and ordinary questions
are not audited, because an audit trail nobody can read is not an audit
trail, and logging everything is the fastest way to get there.

Two rules this table exists to honour:

- **No content, ever.** A row records that a document was uploaded and its
  filename, never its text; that a question was rate-limited, never the
  question. The audit log must stay safe to export and read.
- **No deletes.** Rows survive the user they describe, so `user_id` is
  nullable and not a foreign key - a deleted account must not take its audit
  history with it, which is precisely when that history matters most.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AuditAction:
    """Known action names.

    Plain string constants rather than an Enum: a database enum would need a
    migration for every new audited action, and an unrecognised action in an
    append-only log is harmless.
    """

    LOGIN_SUCCEEDED = "login.succeeded"
    LOGIN_FAILED = "login.failed"
    LOGOUT = "logout"
    REGISTERED = "user.registered"
    ROLE_CHANGED = "user.role_changed"
    PASSWORD_RESET = "user.password_reset"
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_DELETED = "document.deleted"
    KNOWLEDGE_BASE_CLEARED = "knowledge_base.cleared"
    MODEL_CATALOGUE_CHANGED = "model_catalogue.changed"
    RATE_LIMITED = "request.rate_limited"
    AUTHORIZATION_DENIED = "request.authorization_denied"


class AuditEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_events"

    # Not a ForeignKey: the row must outlive the account it refers to.
    user_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)

    # Small, non-sensitive extras (a filename, a reason, a count). Never
    # document text, question text, tokens or credentials.
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True, nullable=False
    )

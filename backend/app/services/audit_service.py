"""Recording and querying audit events.

Writing an audit row must never break the request that triggered it. A
failure to record an event is logged and swallowed: refusing a successful
login because an audit insert failed would turn observability into an outage.
That trade-off is the right one here, and stated plainly rather than hidden.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_extra
from app.db.models.audit import AuditAction, AuditEvent
from app.db.models.user import User

logger = get_logger("app.audit")


class AuditService:
    def record(
        self,
        db: Session,
        action: str,
        *,
        user: Optional[User] = None,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        request_id: Optional[str] = None,
        detail: Optional[dict] = None,
    ) -> None:
        """Append one event. Never raises."""
        try:
            event = AuditEvent(
                user_id=user.id if user else user_id,
                user_email=user.email if user else user_email,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                request_id=request_id,
                detail=detail,
            )
            db.add(event)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to record audit event", extra=log_extra(action=action))

    def list_events(
        self,
        db: Session,
        *,
        action: Optional[str] = None,
        user_email: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditEvent]:
        """Most recent first. Paged, because this table only grows."""
        query = select(AuditEvent).order_by(AuditEvent.created_at.desc())
        if action:
            query = query.where(AuditEvent.action == action)
        if user_email:
            query = query.where(AuditEvent.user_email == user_email)
        return list(db.execute(query.limit(min(limit, 500)).offset(offset)).scalars())


    def list_login_history(
        self, db: Session, *, user_id: str, user_email: str, limit: int = 50
    ) -> List[AuditEvent]:
        """One account's own authentication events, most recent first.

        Matched on id *or* email: a failed login never resolves to a user id
        (the credentials were wrong, so no session was established), and
        those attempts are the entries a user most needs to see.
        """
        query = (
            select(AuditEvent)
            .where(
                AuditEvent.action.in_(
                    [
                        AuditAction.LOGIN_SUCCEEDED,
                        AuditAction.LOGIN_FAILED,
                        AuditAction.LOGOUT,
                        AuditAction.PASSWORD_RESET,
                    ]
                ),
                or_(AuditEvent.user_id == user_id, AuditEvent.user_email == user_email),
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        return list(db.execute(query).scalars())


def get_audit_service() -> AuditService:
    return AuditService()

"""Administrator observability: the audit trail and operational counts.

Both routes are admin-only. The audit trail names who did what and from
where, which is exactly the sort of data that must not be readable by the
people it describes.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentAdmin, DbSession
from app.db.models.audit import AuditAction, AuditEvent
from app.db.models.chat import ChatMessage, ChatSession
from app.db.models.document import Document
from app.db.models.project import Project
from app.db.models.provider_model import ProviderModel
from app.db.models.user import User, UserRole
from app.schemas.admin import (
    AuditEventRead,
    Metrics,
    ProviderModelCreate,
    ProviderModelRead,
    ProviderModelUpdate,
)
from app.schemas.common import APIResponse
from app.services.audit_service import get_audit_service
from app.services.model_catalog import get_model_catalog_service

router = APIRouter(prefix="/admin", tags=["Administration"])


def _to_model_read(row: ProviderModel) -> ProviderModelRead:
    """`kind` is an Enum on the row but a plain string on the wire."""
    return ProviderModelRead(
        id=row.id,
        kind=row.kind.value,
        provider=row.provider,
        model_name=row.model_name,
        display_name=row.display_name,
        is_enabled=row.is_enabled,
        sort_order=row.sort_order,
    )


@router.get("/audit", response_model=APIResponse[List[AuditEventRead]])
def list_audit_events(
    request: Request,
    db: DbSession,
    admin: CurrentAdmin,
    action: Optional[str] = Query(None, description="Filter to one action, e.g. 'login.failed'."),
    user_email: Optional[str] = Query(None, description="Filter to one account."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> APIResponse[List[AuditEventRead]]:
    """Audit events, most recent first. Paged - this table only grows."""
    events = get_audit_service().list_events(
        db, action=action, user_email=user_email, limit=limit, offset=offset
    )
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Audit events retrieved.",
        data=[AuditEventRead.model_validate(event) for event in events],
    )


@router.get("/models", response_model=APIResponse[List[ProviderModelRead]])
def list_models(
    request: Request,
    db: DbSession,
    admin: CurrentAdmin,
    kind: Optional[str] = Query(None, description="Filter to 'chat' or 'embedding'."),
) -> APIResponse[List[ProviderModelRead]]:
    """The full catalogue, including disabled models - this is the editing
    view. End users see only enabled models, via `/providers/*`."""
    rows = get_model_catalog_service().list_all(db, kind=kind)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Models retrieved.",
        data=[_to_model_read(row) for row in rows],
    )


@router.post("/models", response_model=APIResponse[ProviderModelRead], status_code=status.HTTP_201_CREATED)
def add_model(
    payload: ProviderModelCreate, request: Request, db: DbSession, admin: CurrentAdmin
) -> APIResponse[ProviderModelRead]:
    """Make a model selectable without touching code or redeploying."""
    row = get_model_catalog_service().add(
        db,
        kind=payload.kind,
        provider=payload.provider,
        model_name=payload.model_name,
        display_name=payload.display_name,
        sort_order=payload.sort_order,
    )
    get_audit_service().record(
        db,
        AuditAction.MODEL_CATALOGUE_CHANGED,
        user=admin,
        resource_type="provider_model",
        resource_id=row.id,
        request_id=request.state.request_id,
        detail={"action": "added", "kind": payload.kind, "provider": payload.provider, "model": row.model_name},
    )
    return APIResponse.ok(
        request_id=request.state.request_id, message="Model added.", data=_to_model_read(row)
    )


@router.patch("/models/{model_id}", response_model=APIResponse[ProviderModelRead])
def update_model(
    model_id: str,
    payload: ProviderModelUpdate,
    request: Request,
    db: DbSession,
    admin: CurrentAdmin,
) -> APIResponse[ProviderModelRead]:
    row = get_model_catalog_service().update(
        db,
        model_id,
        display_name=payload.display_name,
        is_enabled=payload.is_enabled,
        sort_order=payload.sort_order,
    )
    get_audit_service().record(
        db,
        AuditAction.MODEL_CATALOGUE_CHANGED,
        user=admin,
        resource_type="provider_model",
        resource_id=row.id,
        request_id=request.state.request_id,
        detail={"action": "updated", "model": row.model_name, "enabled": row.is_enabled},
    )
    return APIResponse.ok(
        request_id=request.state.request_id, message="Model updated.", data=_to_model_read(row)
    )


@router.delete("/models/{model_id}", response_model=APIResponse[None])
def delete_model(model_id: str, request: Request, db: DbSession, admin: CurrentAdmin) -> APIResponse[None]:
    """Remove a model entirely.

    Prefer disabling. Documents are indexed into a collection keyed by
    embedding provider and model, so deleting an embedding model that
    documents were indexed with leaves those documents unqueryable.
    """
    service = get_model_catalog_service()
    row = db.get(ProviderModel, model_id)
    detail = (
        {"action": "deleted", "kind": row.kind.value, "provider": row.provider, "model": row.model_name}
        if row
        else {"action": "deleted"}
    )
    service.delete(db, model_id)
    get_audit_service().record(
        db,
        AuditAction.MODEL_CATALOGUE_CHANGED,
        user=admin,
        resource_type="provider_model",
        resource_id=model_id,
        request_id=request.state.request_id,
        detail=detail,
    )
    return APIResponse.ok(request_id=request.state.request_id, message="Model removed.")


@router.post("/models/seed", response_model=APIResponse[int])
def seed_models(request: Request, db: DbSession, admin: CurrentAdmin) -> APIResponse[int]:
    """Add any built-in default models that are missing from the catalogue.

    Additive: it never deletes an operator's own entries and never
    re-enables one they disabled. Useful after upgrading to a version that
    ships support for new models.
    """
    added = get_model_catalog_service().seed_defaults(db)
    return APIResponse.ok(
        request_id=request.state.request_id, message=f"{added} model(s) added.", data=added
    )


@router.get("/metrics", response_model=APIResponse[Metrics])
def get_metrics(request: Request, db: DbSession, admin: CurrentAdmin) -> APIResponse[Metrics]:
    """Operational counts for the whole installation."""

    def count(model, *conditions) -> int:
        query = select(func.count()).select_from(model)
        for condition in conditions:
            query = query.where(condition)
        return db.execute(query).scalar_one()

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    metrics = Metrics(
        users_total=count(User),
        users_admin=count(User, User.role == UserRole.ADMIN),
        documents_total=count(Document),
        # Summed rather than counted: this is chunks indexed, not documents.
        document_chunks_total=db.execute(select(func.coalesce(func.sum(Document.chunk_count), 0))).scalar_one(),
        chat_sessions_total=count(ChatSession),
        chat_messages_total=count(ChatMessage),
        projects_total=count(Project),
        audit_events_total=count(AuditEvent),
        logins_failed_last_24h=count(
            AuditEvent, AuditEvent.action == AuditAction.LOGIN_FAILED, AuditEvent.created_at >= since
        ),
    )
    return APIResponse.ok(
        request_id=request.state.request_id, message="Metrics retrieved.", data=metrics
    )

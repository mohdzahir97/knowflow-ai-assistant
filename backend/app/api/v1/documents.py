"""Knowledge-base management endpoints.

Every route here is administrator-only. The knowledge base is a single
shared corpus: uploading, deleting or clearing it changes the answers every
end user receives, so these operations are not user-scoped and must never be
reachable by an ordinary account.

End users have no document endpoints at all - by design they never learn
which documents exist, and retrieval happens invisibly inside the chat
pipeline.
"""
from typing import List

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from app.api.deps import CurrentAdmin, DbSession
from app.api.rate_limit_deps import rate_limit_upload
from app.core.exceptions import AppError, ValidationAppError
from app.db.models.audit import AuditAction
from app.schemas.common import APIResponse
from app.schemas.document import DocumentRead
from app.services.audit_service import get_audit_service
from app.services.document_service import get_document_service

router = APIRouter(prefix="/documents", tags=["Knowledge Base (Admin)"])


@router.post(
    "/upload",
    response_model=APIResponse[List[DocumentRead]],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_upload)],
)
async def upload_documents(
    request: Request,
    db: DbSession,
    admin: CurrentAdmin,
    files: List[UploadFile] = File(...),
    embedding_provider: str = Form(...),
    embedding_model: str = Form(...),
) -> APIResponse[List[DocumentRead]]:
    """Add one or more PDFs to the shared knowledge base.

    Each file is processed independently: one bad file does not discard the
    good ones, and a file that fails leaves no database row or vectors
    behind. Failures are reported per-file in `errors`.
    """
    service = get_document_service()
    uploaded: List[DocumentRead] = []
    errors: List[str] = []

    audit = get_audit_service()
    for file in files:
        try:
            document = service.upload(db, admin, file, embedding_provider, embedding_model)
            uploaded.append(DocumentRead.model_validate(document))
            # Filename and chunk count only - never the document's text.
            audit.record(
                db,
                AuditAction.DOCUMENT_UPLOADED,
                user=admin,
                resource_type="document",
                resource_id=document.id,
                request_id=request.state.request_id,
                detail={"filename": document.filename, "chunks": document.chunk_count},
            )
        except AppError as exc:
            errors.append(f"{file.filename}: {exc.message}")

    if not uploaded:
        raise ValidationAppError("; ".join(errors) if errors else "No files were provided.")

    message = "Documents uploaded and indexed successfully." if not errors else "Some documents failed to upload."
    return APIResponse.ok(request_id=request.state.request_id, message=message, data=uploaded, errors=errors or None)


@router.get("", response_model=APIResponse[List[DocumentRead]])
def list_documents(request: Request, db: DbSession, admin: CurrentAdmin) -> APIResponse[List[DocumentRead]]:
    """Every document in the knowledge base, regardless of which admin added it."""
    service = get_document_service()
    documents = service.list_documents(db)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Documents retrieved.",
        data=[DocumentRead.model_validate(d) for d in documents],
    )


@router.delete("/{document_id}", response_model=APIResponse[None])
def delete_document(document_id: str, request: Request, db: DbSession, admin: CurrentAdmin) -> APIResponse[None]:
    service = get_document_service()
    service.delete_document(db, document_id)
    get_audit_service().record(
        db,
        AuditAction.DOCUMENT_DELETED,
        user=admin,
        resource_type="document",
        resource_id=document_id,
        request_id=request.state.request_id,
    )
    return APIResponse.ok(request_id=request.state.request_id, message="Document deleted.")


@router.delete("", response_model=APIResponse[None])
def clear_documents(request: Request, db: DbSession, admin: CurrentAdmin) -> APIResponse[None]:
    """Wipe the entire knowledge base. Affects answers for every user."""
    service = get_document_service()
    removed = len(service.list_documents(db))
    service.clear_all(db)
    # The most destructive action in the application, and the one most worth
    # being able to attribute afterwards.
    get_audit_service().record(
        db,
        AuditAction.KNOWLEDGE_BASE_CLEARED,
        user=admin,
        request_id=request.state.request_id,
        detail={"documents_removed": removed},
    )
    return APIResponse.ok(request_id=request.state.request_id, message="Knowledge base cleared.")

"""Knowledge-base management API.

The knowledge base is a single shared corpus curated by administrators, so
these tests cover two distinct concerns:

1. Management behaviour - upload, list, delete, clear - which is admin-only.
2. Authorization - that an ordinary end user is refused server-side, not
   merely hidden from in the UI.
"""


def _upload(client, headers, filename, content, content_type):
    return client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"files": (filename, content, content_type)},
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )


# ---------------------------------------------------------------------------
# Admin management behaviour
# ---------------------------------------------------------------------------


def test_upload_pdf_success(client, admin_headers, sample_pdf_bytes):
    response = _upload(client, admin_headers, "sample.pdf", sample_pdf_bytes, "application/pdf")
    assert response.status_code == 201

    payload = response.json()
    assert payload["success"] is True
    document = payload["data"][0]
    assert document["status"] == "indexed"
    assert document["chunk_count"] > 0
    assert document["page_count"] > 0


def test_upload_rejects_non_pdf(client, admin_headers):
    response = _upload(client, admin_headers, "notes.txt", b"hello world", "text/plain")
    assert response.status_code == 422
    assert response.json()["success"] is False


def test_failed_upload_creates_no_document_record(client, admin_headers):
    """A PDF that fails to parse must leave zero trace - no DB row, no partial record."""
    response = _upload(client, admin_headers, "corrupt.pdf", b"this is not a real pdf file", "application/pdf")
    assert response.status_code == 422
    assert response.json()["success"] is False

    remaining = client.get("/api/v1/documents", headers=admin_headers).json()["data"]
    assert remaining == []


def test_partially_failed_batch_only_saves_the_successful_file(client, admin_headers, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files=[
            ("files", ("sample.pdf", sample_pdf_bytes, "application/pdf")),
            ("files", ("corrupt.pdf", b"not a real pdf", "application/pdf")),
        ],
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert len(payload["data"]) == 1
    assert payload["data"][0]["filename"] == "sample.pdf"
    assert payload["errors"] and "corrupt.pdf" in payload["errors"][0]

    remaining = client.get("/api/v1/documents", headers=admin_headers).json()["data"]
    assert len(remaining) == 1
    assert remaining[0]["filename"] == "sample.pdf"


def test_knowledge_base_is_shared_between_admins(client, admin_headers, sample_pdf_bytes):
    """Documents belong to the knowledge base, not to the admin who uploaded
    them - a second admin must see and be able to manage the same corpus."""
    from tests.conftest import _register_and_login  # noqa: PLC0415
    import uuid

    _upload(client, admin_headers, "sample.pdf", sample_pdf_bytes, "application/pdf")

    from app.db.models.user import User, UserRole
    from app.db.session import SessionLocal

    email = f"admin2-{uuid.uuid4().hex[:8]}@example.com"
    other_admin = _register_and_login(client, email)
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        user.role = UserRole.ADMIN
        db.commit()

    visible = client.get("/api/v1/documents", headers=other_admin).json()["data"]
    assert len(visible) == 1, "a second admin should see the shared knowledge base"


def test_delete_document(client, admin_headers, sample_pdf_bytes):
    upload = _upload(client, admin_headers, "sample.pdf", sample_pdf_bytes, "application/pdf")
    document_id = upload.json()["data"][0]["id"]

    response = client.delete(f"/api/v1/documents/{document_id}", headers=admin_headers)
    assert response.status_code == 200

    remaining = client.get("/api/v1/documents", headers=admin_headers).json()["data"]
    assert all(d["id"] != document_id for d in remaining)


def test_clear_all_documents(client, admin_headers, sample_pdf_bytes):
    _upload(client, admin_headers, "sample.pdf", sample_pdf_bytes, "application/pdf")

    response = client.delete("/api/v1/documents", headers=admin_headers)
    assert response.status_code == 200
    assert client.get("/api/v1/documents", headers=admin_headers).json()["data"] == []


# ---------------------------------------------------------------------------
# Authorization - enforced on the server, not by hiding UI
# ---------------------------------------------------------------------------


def test_upload_requires_authentication(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents/upload",
        files={"files": ("sample.pdf", sample_pdf_bytes, "application/pdf")},
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    assert response.status_code == 401


def test_end_user_cannot_upload_documents(client, auth_headers, sample_pdf_bytes):
    """The headline authorization rule: an ordinary user calling the admin
    API directly must be refused by the backend."""
    response = _upload(client, auth_headers, "sample.pdf", sample_pdf_bytes, "application/pdf")
    assert response.status_code == 403
    assert response.json()["success"] is False


def test_end_user_cannot_list_documents(client, auth_headers):
    """End users must never learn which documents power their answers."""
    assert client.get("/api/v1/documents", headers=auth_headers).status_code == 403


def test_end_user_cannot_delete_documents(client, admin_headers, auth_headers, sample_pdf_bytes):
    upload = _upload(client, admin_headers, "sample.pdf", sample_pdf_bytes, "application/pdf")
    document_id = upload.json()["data"][0]["id"]

    assert client.delete(f"/api/v1/documents/{document_id}", headers=auth_headers).status_code == 403
    # ...and the document must still be there afterwards.
    assert len(client.get("/api/v1/documents", headers=admin_headers).json()["data"]) == 1


def test_end_user_cannot_clear_knowledge_base(client, admin_headers, auth_headers, sample_pdf_bytes):
    _upload(client, admin_headers, "sample.pdf", sample_pdf_bytes, "application/pdf")

    assert client.delete("/api/v1/documents", headers=auth_headers).status_code == 403
    assert len(client.get("/api/v1/documents", headers=admin_headers).json()["data"]) == 1

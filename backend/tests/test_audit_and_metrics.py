"""Audit trail and operational metrics.

The audit trail is only worth having if it records the things that matter
(especially failures), refuses to record the things that must never be
stored, and cannot be read by the people it describes.
"""
import uuid

import pytest

from app.db.models.audit import AuditAction


def _events(client, admin_headers, **params):
    response = client.get("/api/v1/admin/audit", headers=admin_headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_ordinary_users_cannot_read_the_audit_trail(client, auth_headers):
    """It names who did what from which IP - not readable by its subjects."""
    assert client.get("/api/v1/admin/audit", headers=auth_headers).status_code == 403


def test_ordinary_users_cannot_read_metrics(client, auth_headers):
    assert client.get("/api/v1/admin/metrics", headers=auth_headers).status_code == 403


def test_audit_trail_requires_authentication(client):
    assert client.get("/api/v1/admin/audit").status_code == 401


# ---------------------------------------------------------------------------
# What gets recorded
# ---------------------------------------------------------------------------


def test_successful_login_is_recorded(client, admin_headers):
    email = f"audit-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})

    actions = [e["action"] for e in _events(client, admin_headers, user_email=email)]
    assert AuditAction.LOGIN_SUCCEEDED in actions
    assert AuditAction.REGISTERED in actions


def test_failed_login_is_recorded(client, admin_headers):
    """The half that makes credential stuffing visible."""
    email = f"audit-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert response.status_code == 401

    events = _events(client, admin_headers, user_email=email, action=AuditAction.LOGIN_FAILED)
    assert events, "a failed login left no audit trail"


def test_a_failed_login_never_stores_the_password(client, admin_headers):
    email = f"audit-{uuid.uuid4().hex[:10]}@example.com"
    secret = "hunter2-should-never-be-stored"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    client.post("/api/v1/auth/login", json={"email": email, "password": secret})

    serialised = str(_events(client, admin_headers, user_email=email))
    assert secret not in serialised


def test_login_failure_for_an_unknown_account_is_still_recorded(client, admin_headers):
    """Probing for valid accounts is exactly what this should surface."""
    email = f"ghost-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/v1/auth/login", json={"email": email, "password": "whatever123"})
    assert _events(client, admin_headers, user_email=email, action=AuditAction.LOGIN_FAILED)


def test_document_upload_and_deletion_are_recorded_without_content(
    client, admin_headers, sample_pdf_bytes
):
    response = client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files=[("files", ("audited.pdf", sample_pdf_bytes, "application/pdf"))],
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    assert response.status_code == 201, response.text
    document_id = response.json()["data"][0]["id"]

    uploads = _events(client, admin_headers, action=AuditAction.DOCUMENT_UPLOADED)
    mine = [e for e in uploads if e["resource_id"] == document_id]
    assert mine, "upload was not audited"
    # The filename is metadata; the document's text is content and must not appear.
    assert mine[0]["detail"]["filename"] == "audited.pdf"
    assert "paid leave" not in str(mine[0]).lower()

    client.delete(f"/api/v1/documents/{document_id}", headers=admin_headers)
    deletions = _events(client, admin_headers, action=AuditAction.DOCUMENT_DELETED)
    assert any(e["resource_id"] == document_id for e in deletions)


def test_clearing_the_knowledge_base_is_attributable(client, admin_headers, sample_pdf_bytes):
    """The most destructive action, and the one most worth attributing."""
    client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files=[("files", ("doomed.pdf", sample_pdf_bytes, "application/pdf"))],
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    client.delete("/api/v1/documents", headers=admin_headers)

    events = _events(client, admin_headers, action=AuditAction.KNOWLEDGE_BASE_CLEARED)
    assert events
    assert events[0]["user_email"] is not None, "cleared by nobody in particular"
    assert events[0]["detail"]["documents_removed"] >= 1


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------


def test_events_are_returned_most_recent_first(client, admin_headers):
    email = f"order-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})

    events = _events(client, admin_headers, user_email=email)
    timestamps = [e["created_at"] for e in events]
    assert timestamps == sorted(timestamps, reverse=True)


def test_results_are_paged(client, admin_headers):
    first = _events(client, admin_headers, limit=1)
    assert len(first) <= 1
    second = _events(client, admin_headers, limit=1, offset=1)
    if first and second:
        assert first[0]["id"] != second[0]["id"]


@pytest.mark.parametrize("limit", [0, 501])
def test_absurd_page_sizes_are_rejected(client, admin_headers, limit):
    assert client.get(
        "/api/v1/admin/audit", headers=admin_headers, params={"limit": limit}
    ).status_code == 422


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metrics_report_real_counts(client, admin_headers, sample_pdf_bytes):
    client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files=[("files", ("counted.pdf", sample_pdf_bytes, "application/pdf"))],
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )

    response = client.get("/api/v1/admin/metrics", headers=admin_headers)
    assert response.status_code == 200
    metrics = response.json()["data"]

    assert metrics["documents_total"] >= 1
    assert metrics["document_chunks_total"] >= 1, "chunks are summed, not counted as documents"
    assert metrics["users_total"] >= 1
    assert metrics["users_admin"] >= 1
    assert metrics["audit_events_total"] >= 1


def test_failed_login_metric_tracks_the_audit_trail(client, admin_headers):
    before = client.get("/api/v1/admin/metrics", headers=admin_headers).json()["data"][
        "logins_failed_last_24h"
    ]
    client.post(
        "/api/v1/auth/login",
        json={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com", "password": "wrong-password"},
    )
    after = client.get("/api/v1/admin/metrics", headers=admin_headers).json()["data"][
        "logins_failed_last_24h"
    ]
    assert after == before + 1

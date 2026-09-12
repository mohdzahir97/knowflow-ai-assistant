"""Phase 0 stabilization regressions.

Covers the database-level invariants and housekeeping added during
stabilization: the unique document-session constraint that closes the
create-session race, expired-token pruning, and the SQLite pragmas that
make a separate background-indexing process viable.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.base import generate_uuid
from app.db.models.chat import ChatSession
from app.db.models.document import Document, DocumentStatus
from app.db.models.revoked_token import RevokedToken
from app.db.models.user import User
from app.db.session import SessionLocal, engine
from app.services.auth_service import get_auth_service


@pytest.fixture
def db_session(client):
    """A DB session bound to the same engine the app uses.

    Depends on `client` so the schema is guaranteed to exist first.
    """
    with SessionLocal() as session:
        yield session


@pytest.fixture
def user(db_session) -> User:
    from app.core.security import hash_password

    record = User(email=f"stab-{generate_uuid()[:8]}@example.com", hashed_password=hash_password("password123"))
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def _make_document(db_session, owner: User) -> Document:
    """A minimal INDEXED document row, so chat sessions have a real FK target."""
    document = Document(
        user_id=owner.id,
        filename="stab.pdf",
        stored_path="/tmp/stab.pdf",
        content_type="application/pdf",
        file_size_bytes=1,
        status=DocumentStatus.INDEXED,
        embedding_provider="testembed",
        embedding_model="fake-embed-model",
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)
    return document


def test_sqlite_pragmas_applied(client):
    """WAL + busy_timeout are what let a background worker write to the same
    file as the API without instantly failing on 'database is locked'."""
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        # SQLite ignores FK constraints unless explicitly enabled per connection.
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_dangling_document_reference_rejected(db_session, user):
    """With foreign_keys=ON, a chat session can no longer point at a
    document that does not exist. Before this pragma SQLite accepted the
    dangling reference silently."""
    db_session.add(ChatSession(user_id=user.id, document_id=generate_uuid(), title="orphan"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_duplicate_document_session_rejected_by_database(db_session, user):
    """The invariant must hold in the schema, not just in service code — a
    SELECT-then-INSERT check alone loses the race under concurrency."""
    document = _make_document(db_session, user)
    document_id = document.id
    db_session.add(ChatSession(user_id=user.id, document_id=document_id, title="first"))
    db_session.commit()

    db_session.add(ChatSession(user_id=user.id, document_id=document_id, title="second"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_multiple_general_sessions_still_allowed(db_session, user):
    """General (non-document) sessions have document_id NULL, and NULLs are
    distinct in a unique index — so the constraint must not restrict them."""
    for index in range(3):
        db_session.add(ChatSession(user_id=user.id, document_id=None, title=f"general {index}"))
    db_session.commit()

    count = (
        db_session.query(ChatSession)
        .filter(ChatSession.user_id == user.id, ChatSession.document_id.is_(None))
        .count()
    )
    assert count == 3


def test_prune_expired_tokens_removes_only_expired(db_session, user):
    now = datetime.now(timezone.utc)
    expired_jti, live_jti = generate_uuid(), generate_uuid()

    db_session.add(RevokedToken(jti=expired_jti, user_id=user.id, expires_at=now - timedelta(hours=1)))
    db_session.add(RevokedToken(jti=live_jti, user_id=user.id, expires_at=now + timedelta(hours=1)))
    db_session.commit()

    get_auth_service().prune_expired_tokens(db_session)

    assert db_session.get(RevokedToken, expired_jti) is None, "expired revocation should be pruned"
    assert db_session.get(RevokedToken, live_jti) is not None, "unexpired revocation must be kept"


def test_logged_out_token_still_rejected_after_pruning(client):
    """Pruning must never resurrect a still-valid logged-out token."""
    email = f"prune-{generate_uuid()[:8]}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["data"]
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    client.post("/api/v1/auth/logout", headers=headers, json={"refresh_token": tokens["refresh_token"]})

    with SessionLocal() as session:
        get_auth_service().prune_expired_tokens(session)

    # The access token has not expired yet, so its revocation row must survive.
    assert client.get("/api/v1/documents", headers=headers).status_code == 401

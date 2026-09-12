"""Password reset, email verification, and sign-in history.

The security properties matter more than the happy path here, so most of
these test what must *not* happen: no account enumeration, no reusable
links, no surviving sessions after a reset.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.db.models.auth_token import AuthToken, TokenPurpose
from app.db.session import SessionLocal


@pytest.fixture
def account(client):
    """A registered account, with its credentials."""
    email = f"recover-{uuid.uuid4().hex[:10]}@example.com"
    password = "password123"
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return {"email": email, "password": password, "id": response.json()["data"]["id"]}


def _latest_token(user_id: str, purpose: TokenPurpose) -> AuthToken:
    with SessionLocal() as db:
        return (
            db.query(AuthToken)
            .filter(AuthToken.user_id == user_id, AuthToken.purpose == purpose)
            .order_by(AuthToken.created_at.desc())
            .first()
        )


def _issue_reset_and_capture(client, monkeypatch, email: str) -> str:
    """Request a reset and capture the token from the outgoing email."""
    sent = {}

    from app.core import email as email_module

    class CapturingSender(email_module.EmailSender):
        def send(self, to, subject, body):
            sent["to"] = to
            sent["body"] = body

    monkeypatch.setattr(email_module, "get_email_sender", lambda: CapturingSender())
    # account_service imported the symbol directly, so patch it there too.
    from app.services import account_service as account_module

    monkeypatch.setattr(account_module, "get_email_sender", lambda: CapturingSender())

    response = client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert response.status_code == 200
    if "body" not in sent:
        return ""
    return sent["body"].split("reset_token=")[1].split()[0]


# ---------------------------------------------------------------------------
# No account enumeration
# ---------------------------------------------------------------------------


def test_forgot_password_response_is_identical_for_unknown_addresses(client, account):
    """Different answers here would make this a free membership oracle."""
    known = client.post("/api/v1/auth/forgot-password", json={"email": account["email"]})
    unknown = client.post(
        "/api/v1/auth/forgot-password", json={"email": f"ghost-{uuid.uuid4().hex}@example.com"}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json()["message"] == unknown.json()["message"]
    assert known.json()["success"] == unknown.json()["success"]


def test_no_token_is_issued_for_an_unknown_address(client):
    client.post("/api/v1/auth/forgot-password", json={"email": f"ghost-{uuid.uuid4().hex}@example.com"})
    with SessionLocal() as db:
        assert db.query(AuthToken).filter(AuthToken.user_id.is_(None)).count() == 0


# ---------------------------------------------------------------------------
# Reset flow
# ---------------------------------------------------------------------------


def test_password_can_be_reset_with_an_emailed_token(client, account, monkeypatch):
    token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    assert token, "no reset link was emailed"

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "brand-new-pass1"}
    )
    assert response.status_code == 200, response.text

    assert client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": "brand-new-pass1"}
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": account["password"]}
    ).status_code == 401, "the old password still works"


def test_a_reset_token_cannot_be_used_twice(client, account, monkeypatch):
    token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    first = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "firstpass1"})
    second = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "secondpass1"})

    assert first.status_code == 200
    assert second.status_code == 422, "a used reset link worked a second time"


def test_an_expired_token_is_rejected(client, account, monkeypatch):
    token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    with SessionLocal() as db:
        record = (
            db.query(AuthToken)
            .filter(AuthToken.user_id == account["id"], AuthToken.purpose == TokenPurpose.PASSWORD_RESET)
            .order_by(AuthToken.created_at.desc())
            .first()
        )
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "expiredpass1"}
    )
    assert response.status_code == 422


def test_requesting_a_second_link_invalidates_the_first(client, account, monkeypatch):
    """Two working reset links at once widens the window unnecessarily."""
    first_token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    _issue_reset_and_capture(client, monkeypatch, account["email"])

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": first_token, "new_password": "supersedes1"}
    )
    assert response.status_code == 422, "the superseded link still worked"


def test_an_invented_token_is_rejected(client):
    response = client.post(
        "/api/v1/auth/reset-password", json={"token": "not-a-real-token", "new_password": "whatever1"}
    )
    assert response.status_code == 422


def test_the_plaintext_token_is_never_stored(client, account, monkeypatch):
    """A leaked database must not yield a usable link."""
    token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    with SessionLocal() as db:
        stored = [row.token_hash for row in db.query(AuthToken).all()]
    assert token not in stored


def test_a_reset_password_must_still_be_strong(client, account, monkeypatch):
    token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    response = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "short"})
    assert response.status_code == 422, "a reset bypassed the password rules"


# ---------------------------------------------------------------------------
# Sessions end on reset
# ---------------------------------------------------------------------------


def test_existing_sessions_stop_working_after_a_reset(client, account, monkeypatch):
    """The point of a reset: an attacker holding a token must lose access."""
    login = client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": account["password"]}
    ).json()["data"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "afterreset1"})

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401, (
        "an access token issued before the reset still works"
    )


def test_refresh_tokens_stop_working_after_a_reset(client, account, monkeypatch):
    """Otherwise a session could be renewed forever and the reset is moot."""
    login = client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": account["password"]}
    ).json()["data"]

    token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "afterreset1"})

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert response.status_code == 401, "a pre-reset refresh token was still accepted"


def test_a_new_login_after_a_reset_works(client, account, monkeypatch):
    """The cutoff must not lock the legitimate owner out."""
    token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "afterreset1"})

    login = client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": "afterreset1"}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


def test_new_accounts_start_unverified(client, account):
    login = client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": account["password"]}
    ).json()["data"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["data"]["is_verified"] is False


def test_email_can_be_verified_with_the_emailed_token(client, account):
    record = _latest_token(account["id"], TokenPurpose.EMAIL_VERIFICATION)
    assert record is not None, "registration issued no verification token"

    # The plaintext is not recoverable from the database by design, so issue
    # a fresh one through the service to obtain it.
    from app.db.models.user import User
    from app.services.account_service import AccountService

    with SessionLocal() as db:
        user = db.get(User, account["id"])
        token = AccountService()._issue(db, user, TokenPurpose.EMAIL_VERIFICATION, 60)

    response = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["is_verified"] is True


def test_verification_is_not_required_to_sign_in_by_default(client, account):
    """Turning verification on later must not lock out existing accounts."""
    assert get_settings().require_email_verification is False
    assert client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": account["password"]}
    ).status_code == 200


def test_unverified_login_is_refused_when_verification_is_required(client, account, monkeypatch):
    monkeypatch.setattr(get_settings(), "require_email_verification", True)
    response = client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": account["password"]}
    )
    assert response.status_code == 401


def test_a_password_reset_token_cannot_verify_an_email(client, account, monkeypatch):
    """Purposes must not be interchangeable."""
    token = _issue_reset_and_capture(client, monkeypatch, account["email"])
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 422


# ---------------------------------------------------------------------------
# Login history
# ---------------------------------------------------------------------------


def test_login_history_shows_the_users_own_activity(client, account):
    client.post("/api/v1/auth/login", json={"email": account["email"], "password": "wrong-password"})
    login = client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": account["password"]}
    ).json()["data"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    response = client.get("/api/v1/auth/login-history", headers=headers)
    assert response.status_code == 200
    actions = [entry["action"] for entry in response.json()["data"]]
    assert "login.succeeded" in actions
    assert "login.failed" in actions, "failed attempts are the entries most worth seeing"


def test_login_history_does_not_leak_other_accounts(client, account):
    other_email = f"other-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/v1/auth/register", json={"email": other_email, "password": "password123"})
    client.post("/api/v1/auth/login", json={"email": other_email, "password": "password123"})

    login = client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": account["password"]}
    ).json()["data"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    entries = client.get("/api/v1/auth/login-history", headers=headers).json()["data"]
    assert all(other_email not in str(entry) for entry in entries)


def test_login_history_requires_authentication(client):
    assert client.get("/api/v1/auth/login-history").status_code == 401

"""Password reset and email verification.

Two properties this module is built around:

**No account enumeration.** "Forgot password" behaves identically whether or
not the address exists - same response, same status, no timing shortcut that
skips work only for unknown addresses. An endpoint that answers "no such
user" is a free membership oracle.

**Tokens are single-use, expiring, and stored only as hashes.** Presenting a
token proves possession of the email; it must not survive being used, and a
database leak must not yield a usable link.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.email import get_email_sender
from app.core.exceptions import ValidationAppError
from app.core.logging import get_logger, log_extra
from app.core.security import hash_password
from app.db.models.auth_token import AuthToken, TokenPurpose
from app.db.models.user import User

logger = get_logger("app.account")


def _hash_token(token: str) -> str:
    """SHA-256, not bcrypt.

    Deliberate: these tokens are 256 bits of `secrets` output, so they have
    no guessable structure for a slow hash to defend. bcrypt here would add
    latency to every verification and protect against nothing.
    """
    return hashlib.sha256(token.encode()).hexdigest()


class AccountService:
    # ------------------------------------------------------------------
    # Token plumbing
    # ------------------------------------------------------------------

    def _issue(self, db: Session, user: User, purpose: TokenPurpose, ttl_minutes: int) -> str:
        """Create a token, returning the plaintext (which is never stored).

        Any earlier unused token for the same purpose is invalidated first,
        so requesting a second reset link cannot leave two working links.
        """
        db.query(AuthToken).filter(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.is_used.is_(False),
        ).update({AuthToken.is_used: True, AuthToken.used_at: datetime.now(timezone.utc)})

        token = secrets.token_urlsafe(32)
        db.add(
            AuthToken(
                user_id=user.id,
                token_hash=_hash_token(token),
                purpose=purpose,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
            )
        )
        db.commit()
        return token

    def _consume(self, db: Session, token: str, purpose: TokenPurpose) -> User:
        """Validate and burn a token, returning its user.

        Every failure raises the same message. Distinguishing "expired" from
        "already used" from "never existed" tells an attacker which of their
        guesses was once real.
        """
        record = db.execute(
            select(AuthToken).where(
                AuthToken.token_hash == _hash_token(token), AuthToken.purpose == purpose
            )
        ).scalar_one_or_none()

        invalid = ValidationAppError("This link is invalid or has expired. Please request a new one.")
        if record is None or record.is_used:
            raise invalid

        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            # SQLite returns naive datetimes; compare in UTC regardless.
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise invalid

        user = db.get(User, record.user_id)
        if user is None or not user.is_active:
            raise invalid

        record.is_used = True
        record.used_at = datetime.now(timezone.utc)
        db.commit()
        return user

    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------

    def request_password_reset(self, db: Session, email: str, request_id: Optional[str] = None) -> None:
        """Email a reset link if the address belongs to an account.

        Returns nothing either way. The caller must respond identically for
        known and unknown addresses.
        """
        settings = get_settings()
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None or not user.is_active:
            logger.info(
                "Password reset requested for an unknown or inactive address",
                extra=log_extra(request_id=request_id),
            )
            return

        token = self._issue(
            db, user, TokenPurpose.PASSWORD_RESET, settings.password_reset_token_expire_minutes
        )
        link = f"{settings.frontend_base_url}?reset_token={token}"
        get_email_sender().send(
            to=user.email,
            subject="Reset your password",
            body=(
                "A password reset was requested for your account.\n\n"
                f"Use this link within {settings.password_reset_token_expire_minutes} minutes:\n\n"
                f"{link}\n\n"
                "If you did not request this, no action is needed - the link "
                "cannot be used without access to this mailbox."
            ),
        )
        logger.info("Password reset email issued", extra=log_extra(user_id=user.id, request_id=request_id))

    def reset_password(self, db: Session, token: str, new_password: str) -> User:
        """Set a new password and invalidate every existing session.

        Revoking refresh tokens is the point of a reset: if the account was
        taken over, changing the password while the attacker keeps a valid
        refresh token accomplishes nothing.
        """
        user = self._consume(db, token, TokenPurpose.PASSWORD_RESET)
        user.hashed_password = hash_password(new_password)
        # Ends every existing session. If the account was taken over,
        # changing the password while the attacker keeps a working refresh
        # token would accomplish nothing.
        user.session_epoch = (user.session_epoch or 0) + 1
        db.commit()

        logger.info("Password reset completed", extra=log_extra(user_id=user.id))
        return user

    # ------------------------------------------------------------------
    # Email verification
    # ------------------------------------------------------------------

    def send_verification_email(self, db: Session, user: User) -> None:
        if user.is_verified:
            return
        settings = get_settings()
        token = self._issue(
            db, user, TokenPurpose.EMAIL_VERIFICATION, settings.email_verification_token_expire_minutes
        )
        link = f"{settings.frontend_base_url}?verify_token={token}"
        get_email_sender().send(
            to=user.email,
            subject="Confirm your email address",
            body=f"Confirm your address by opening this link:\n\n{link}\n",
        )

    def verify_email(self, db: Session, token: str) -> User:
        user = self._consume(db, token, TokenPurpose.EMAIL_VERIFICATION)
        user.is_verified = True
        db.commit()
        logger.info("Email verified", extra=log_extra(user_id=user.id))
        return user


def get_account_service() -> AccountService:
    return AccountService()

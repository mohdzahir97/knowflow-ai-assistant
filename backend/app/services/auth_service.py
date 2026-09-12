"""Business logic for registration, login, token refresh, and logout."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidCredentialsError, TokenError, UserAlreadyExistsError
from app.core.logging import get_logger, log_extra
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.config import get_settings
from app.db.models.revoked_token import RevokedToken
from app.db.models.user import User
from app.schemas.auth import TokenPair, UserCreate

logger = get_logger("app.auth")
settings = get_settings()


class AuthService:
    """Encapsulates all authentication use cases. Stateless — a DB session
    is passed per call so this can be safely used as a request-scoped
    dependency without holding connections between requests.
    """

    def register(self, db: Session, payload: UserCreate) -> User:
        existing = db.scalar(select(User).where(User.email == payload.email))
        if existing:
            raise UserAlreadyExistsError()

        user = User(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("User registered", extra=log_extra(user_id=user.id))
        return user

    def authenticate(self, db: Session, email: str, password: str) -> User:
        user = db.scalar(select(User).where(User.email == email))
        if not user or not verify_password(password, user.hashed_password):
            logger.warning("Failed login attempt", extra=log_extra(email=email))
            raise InvalidCredentialsError()
        if not user.is_active:
            raise InvalidCredentialsError("This account has been deactivated.")
        # Checked after the password, deliberately: reporting "unverified"
        # to someone who supplied the wrong password would confirm the
        # address exists.
        if settings.require_email_verification and not user.is_verified:
            raise InvalidCredentialsError(
                "Please confirm your email address before signing in. Check your inbox for the link."
            )
        return user

    def issue_token_pair(self, user: User) -> TokenPair:
        access_token, _, _ = create_access_token(user.id, user.session_epoch)
        refresh_token, _, _ = create_refresh_token(user.id, user.session_epoch)
        logger.info("Token pair issued", extra=log_extra(user_id=user.id))
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    def refresh(self, db: Session, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token)
        if payload.get("type") != TokenType.REFRESH.value:
            raise TokenError("Provided token is not a refresh token.")

        jti = payload["jti"]
        if db.get(RevokedToken, jti):
            raise TokenError("This token has been revoked.")

        user_id = payload["sub"]
        user = db.get(User, user_id)
        if not user or not user.is_active:
            raise TokenError("User no longer exists or is inactive.")

        # Checked here as well as on the access path: a password reset that
        # left refresh tokens working would let a session be renewed forever,
        # which defeats the reset entirely.
        from app.api.deps import is_session_invalidated

        if is_session_invalidated(user, payload):
            raise TokenError("This session has ended. Please sign in again.")

        access_token, _, _ = create_access_token(user.id, user.session_epoch)
        new_refresh_token, _, _ = create_refresh_token(user.id, user.session_epoch)

        self._revoke(db, jti, user_id, payload["exp"])
        logger.info("Token refreshed", extra=log_extra(user_id=user_id))
        return TokenPair(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    def logout(self, db: Session, access_payload: dict, refresh_token: str) -> None:
        user_id = access_payload["sub"]
        self._revoke(db, access_payload["jti"], user_id, access_payload["exp"])

        refresh_payload = decode_token(refresh_token)
        if refresh_payload.get("type") != TokenType.REFRESH.value:
            raise TokenError("Provided token is not a refresh token.")
        if refresh_payload["sub"] != user_id:
            raise TokenError("Refresh token does not belong to the authenticated user.")
        self._revoke(db, refresh_payload["jti"], user_id, refresh_payload["exp"])

        logger.info("User logged out", extra=log_extra(user_id=user_id))

    def _revoke(self, db: Session, jti: str, user_id: str, exp: int) -> None:
        if db.get(RevokedToken, jti):
            return
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        db.add(RevokedToken(jti=jti, user_id=user_id, expires_at=expires_at))
        db.commit()

    def prune_expired_tokens(self, db: Session) -> int:
        """Delete revocation records whose tokens have already expired.

        The table only exists to reject tokens that are still within their
        validity window; once a token has expired it is refused by signature
        verification anyway, so the row serves no purpose. Without this the
        table grows by two rows per logout forever.

        Returns the number of rows removed.
        """
        now = datetime.now(timezone.utc)
        deleted = db.query(RevokedToken).filter(RevokedToken.expires_at < now).delete(synchronize_session=False)
        db.commit()
        if deleted:
            logger.info("Pruned expired revoked tokens", extra=log_extra(deleted_count=deleted))
        return deleted


def get_auth_service() -> AuthService:
    return AuthService()

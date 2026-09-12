"""Shared FastAPI dependencies: DB session, current user, current token."""
from typing import Annotated, Any, Dict

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, TokenError
from app.core.logging import get_logger, log_extra
from app.core.security import TokenType, decode_token
from app.db.models.revoked_token import RevokedToken
from app.db.models.user import User, UserRole
from app.db.session import get_db

logger = get_logger("app.authz")

_bearer_scheme = HTTPBearer(auto_error=True)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    db: DbSession,
) -> Dict[str, Any]:
    payload = decode_token(credentials.credentials)
    if payload.get("type") != TokenType.ACCESS.value:
        raise TokenError("An access token is required for this operation.")
    if db.get(RevokedToken, payload["jti"]):
        raise TokenError("This token has been revoked.")
    return payload


def get_current_user(
    payload: Annotated[Dict[str, Any], Depends(get_current_token_payload)],
    db: DbSession,
) -> User:
    user = db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise TokenError("User no longer exists or is inactive.")
    if is_session_invalidated(user, payload):
        raise TokenError("This session has ended. Please sign in again.")
    return user


def is_session_invalidated(user: User, payload: Dict[str, Any]) -> bool:
    """True when the token was issued under a superseded session epoch.

    A password reset bumps the user's epoch, so every token minted before it
    stops working - including ones an attacker is holding. Tokens predating
    this claim default to epoch 0, which matches every untouched account.
    """
    return payload.get("sev", 0) != user.session_epoch


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Reject anyone who is not an administrator.

    This is the only authorization that counts. The frontend hides admin
    navigation from ordinary users, but that is presentation, not security -
    a user who calls an admin endpoint directly must still be refused here.

    Returns 403 (authenticated, but not permitted) rather than 404, because
    the existence of the admin API is not itself a secret; what matters is
    that acting on it is refused.
    """
    if user.role != UserRole.ADMIN:
        logger.warning(
            "Admin endpoint refused for non-admin user",
            extra=log_extra(user_id=user.id, role=getattr(user.role, "value", str(user.role))),
        )
        raise AuthorizationError("This action requires administrator privileges.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(require_admin)]
CurrentTokenPayload = Annotated[Dict[str, Any], Depends(get_current_token_payload)]

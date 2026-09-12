"""Password hashing (bcrypt) and JWT issuance/verification.

This is the only module that should touch `bcrypt` or `jose` directly —
services depend on the functions here, not on the underlying libraries,
so the hashing/token scheme can be swapped without touching callers.
"""
import enum
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import TokenError

settings = get_settings()


class TokenType(str, enum.Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def _create_token(
    subject: str, token_type: TokenType, expires_delta: timedelta, session_epoch: int = 0
) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + expires_delta
    jti = str(uuid.uuid4())
    payload: Dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": expires_at,
        "jti": jti,
        # The user's session epoch when this was minted. A password reset
        # bumps the user's epoch, which makes every token carrying an older
        # one invalid without needing to know their jti values.
        "sev": session_epoch,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti, expires_at


def create_access_token(user_id: str, session_epoch: int = 0) -> tuple[str, str, datetime]:
    return _create_token(
        user_id, TokenType.ACCESS, timedelta(minutes=settings.access_token_expire_minutes), session_epoch
    )


def create_refresh_token(user_id: str, session_epoch: int = 0) -> tuple[str, str, datetime]:
    return _create_token(
        user_id, TokenType.REFRESH, timedelta(minutes=settings.refresh_token_expire_minutes), session_epoch
    )


def decode_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise TokenError("Invalid or expired token.") from exc
    return payload

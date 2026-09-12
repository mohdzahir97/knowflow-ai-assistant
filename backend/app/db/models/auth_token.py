"""Single-use tokens for password reset and email verification.

Only a hash of each token is stored. The plaintext exists in the email and
nowhere else, so a leaked database yields nothing an attacker can present -
the same reasoning that applies to passwords, and for the same reason.

One table serves both purposes, distinguished by `purpose`. Two near
identical tables would duplicate the issue/verify/consume logic for no gain.
"""
import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class TokenPurpose(str, enum.Enum):
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"


class AuthToken(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "auth_tokens"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    # SHA-256 of the token that was emailed. Indexed because lookup is by hash.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    purpose: Mapped[TokenPurpose] = mapped_column(Enum(TokenPurpose), index=True, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Kept rather than deleted on use, so a replayed link can be told apart
    # from one that never existed when investigating.
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

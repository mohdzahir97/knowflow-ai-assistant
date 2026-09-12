"""User model.

Designed so external identity providers (OAuth/OIDC/SSO) can be bolted on
later via an additional `auth_provider` / `external_id` pair without
altering existing columns or breaking current local-auth users.
"""
import enum
from typing import List, Optional

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(str, enum.Enum):
    """Who may manage the knowledge base versus merely consume it.

    ADMIN curates the shared knowledge base: uploading, re-indexing and
    removing documents, and testing retrieval against individual documents.
    USER asks questions and owns their own chats, but has no visibility of
    documents at all - the retrieval layer is invisible to them by design.

    Enforced server-side on every admin route; hiding navigation is not
    authorization.
    """

    ADMIN = "admin"
    USER = "user"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Whether the address has been confirmed by following an emailed link.
    # Login does not require it unless REQUIRE_EMAIL_VERIFICATION is on, so
    # enabling verification never locks out accounts that predate it.
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Bumped to end every existing session at once. Each token carries the
    # epoch it was issued under, and any token whose epoch differs is
    # rejected.
    #
    # A counter rather than a "valid from" timestamp on purpose: JWT `iat` is
    # an integer number of seconds, so a timestamp cutoff cannot order a
    # token against a reset that happened in the same second - it either
    # rejects the token the user just obtained, or keeps honouring one issued
    # moments before. A counter has no granularity to lose.
    #
    # The revocation table cannot do this job: it is a denylist of individual
    # jti values, and the jtis of tokens already in the wild were never
    # recorded.
    session_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # New accounts are USER by default: self-signup must never be able to
    # grant knowledge-base management rights.
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER, nullable=False, index=True)

    # Reserved for future external-provider support (e.g. "local", "google", "github").
    auth_provider: Mapped[str] = mapped_column(String(50), default="local", nullable=False)

    documents: Mapped[List["Document"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    chat_sessions: Mapped[List["ChatSession"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    projects: Mapped[List["Project"]] = relationship(back_populates="owner", cascade="all, delete-orphan")

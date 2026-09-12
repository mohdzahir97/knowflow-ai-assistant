"""Chat session and message models — per-user conversation history."""
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.document import Document
    from app.db.models.project import Project
    from app.db.models.user import User


class ChatSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        # At most one document-scoped session per user per document. NULL
        # document_id (general chat) is exempt, since NULLs compare as
        # distinct in a unique index.
        UniqueConstraint("user_id", "document_id", name="uq_chat_sessions_user_document"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="New Chat", nullable=False)
    # Set when this conversation is scoped to a single document (see
    # "chat with this document"). Null means a general session whose
    # retrieval spans every document under the request's embedding config.
    # There is at most one document-scoped session per (user, document).
    document_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # Optional grouping. SET NULL rather than CASCADE: deleting a project is
    # an organisational action and must never destroy conversations.
    project_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )

    owner: Mapped["User"] = relationship(back_populates="chat_sessions")
    document: Mapped[Optional["Document"]] = relationship(back_populates="chat_sessions")
    project: Mapped[Optional["Project"]] = relationship(back_populates="chats")
    messages: Mapped[List["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chat_messages"

    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")

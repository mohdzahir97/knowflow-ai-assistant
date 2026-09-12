"""Which models each provider offers - configuration, not code.

Model line-ups change constantly: providers deprecate names, add new ones,
and an operator may want to restrict their installation to an approved
subset. None of that should require editing Python and redeploying, so the
catalogue lives here and is editable by an administrator at runtime.

The provider *classes* still declare `default_models`. That list is seed
data - what a fresh installation starts with - not the source of truth. Once
the catalogue has any rows, the database wins.
"""
import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class ModelKind(str, enum.Enum):
    """Chat and embedding models are separate namespaces.

    The same provider can offer both, and a name is only meaningful within
    its kind - asking an embedding model to chat is a configuration error
    worth making unrepresentable.
    """

    CHAT = "chat"
    EMBEDDING = "embedding"


class ProviderModel(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "provider_models"
    __table_args__ = (
        UniqueConstraint("kind", "provider", "model_name", name="uq_provider_models_identity"),
    )

    kind: Mapped[ModelKind] = mapped_column(Enum(ModelKind), index=True, nullable=False)
    # Matches the name a provider is registered under (e.g. "openai").
    # Not a foreign key: providers are code, not rows.
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Optional friendlier label for the UI; the raw name is shown when unset.
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Disabling hides a model without losing it - the usual case is a
    # deprecated model that existing documents were indexed with, where
    # deleting the row would make those documents unqueryable.
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

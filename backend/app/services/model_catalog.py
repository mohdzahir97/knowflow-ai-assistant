"""Reads and edits the model catalogue.

Why there is a cache
--------------------
`validate_model` runs on every chat request and every upload, on provider
objects that hold no database session. Opening a session per validation
would put a query in the hot path of every question asked. So the catalogue
is read once into memory and re-read only when an administrator changes it.

Why an unseeded catalogue falls back to code
--------------------------------------------
A brand-new database has no rows, and an application that refuses every
model until someone seeds it is broken out of the box. So an *entirely
empty* table means "not configured yet, use the defaults the provider
classes declare". As soon as the table has any row, the database is
authoritative - otherwise disabling the last model of a provider would
silently resurrect the built-in list, and an operator restricting their
installation to an approved subset would find their restriction ignored.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundError, ValidationAppError
from app.core.logging import get_logger, log_extra
from app.db.models.provider_model import ModelKind, ProviderModel
from app.db.session import SessionLocal

logger = get_logger("app.models")

# (kind, provider) -> ordered model names. None means "not loaded yet".
_cache: Optional[Dict[Tuple[str, str], List[str]]] = None
_seeded = False
_lock = threading.Lock()


def _load() -> Dict[Tuple[str, str], List[str]]:
    """Read the whole catalogue. Small by nature - a few dozen rows."""
    global _seeded
    with SessionLocal() as db:
        rows = db.execute(
            select(ProviderModel).order_by(ProviderModel.sort_order, ProviderModel.model_name)
        ).scalars().all()

        # Seeded-ness is about the table having any row at all, including
        # disabled ones: an operator who disabled everything meant it.
        _seeded = bool(rows)

        catalogue: Dict[Tuple[str, str], List[str]] = {}
        for row in rows:
            if not row.is_enabled:
                continue
            catalogue.setdefault((row.kind.value, row.provider), []).append(row.model_name)
        return catalogue


def _ensure_loaded() -> Dict[Tuple[str, str], List[str]]:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = _load()
    return _cache


def invalidate() -> None:
    """Drop the cache so the next read reflects a change."""
    global _cache
    with _lock:
        _cache = None


def models_for(kind: str, provider: str, defaults: List[str]) -> List[str]:
    """Enabled model names for one provider, or `defaults` if unseeded."""
    catalogue = _ensure_loaded()
    if not _seeded:
        return list(defaults)
    return list(catalogue.get((kind, provider), []))


class ModelCatalogService:
    """Administrative CRUD over the catalogue."""

    def list_all(self, db: Session, kind: Optional[str] = None) -> List[ProviderModel]:
        """Every row including disabled ones - this is the editing view."""
        query = select(ProviderModel).order_by(
            ProviderModel.kind, ProviderModel.provider, ProviderModel.sort_order, ProviderModel.model_name
        )
        if kind:
            query = query.where(ProviderModel.kind == ModelKind(kind))
        return list(db.execute(query).scalars())

    def add(
        self,
        db: Session,
        *,
        kind: str,
        provider: str,
        model_name: str,
        display_name: Optional[str] = None,
        sort_order: int = 0,
    ) -> ProviderModel:
        self._require_known_provider(kind, provider)

        row = ProviderModel(
            kind=ModelKind(kind),
            provider=provider,
            model_name=model_name.strip(),
            display_name=display_name,
            sort_order=sort_order,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ValidationAppError(f"'{model_name}' is already configured for {provider} ({kind}).")
        db.refresh(row)
        invalidate()
        logger.info(
            "Model added to catalogue", extra=log_extra(kind=kind, provider=provider, model=model_name)
        )
        return row

    def update(
        self,
        db: Session,
        model_id: str,
        *,
        display_name: Optional[str] = None,
        is_enabled: Optional[bool] = None,
        sort_order: Optional[int] = None,
    ) -> ProviderModel:
        row = db.get(ProviderModel, model_id)
        if row is None:
            raise ResourceNotFoundError("Model not found.")

        if display_name is not None:
            row.display_name = display_name or None
        if is_enabled is not None:
            row.is_enabled = is_enabled
        if sort_order is not None:
            row.sort_order = sort_order

        db.commit()
        db.refresh(row)
        invalidate()
        return row

    def delete(self, db: Session, model_id: str) -> None:
        row = db.get(ProviderModel, model_id)
        if row is None:
            raise ResourceNotFoundError("Model not found.")
        db.delete(row)
        db.commit()
        invalidate()
        logger.info(
            "Model removed from catalogue",
            extra=log_extra(kind=row.kind.value, provider=row.provider, model=row.model_name),
        )

    def seed_defaults(self, db: Session, overwrite: bool = False) -> int:
        """Insert each provider's declared defaults, skipping ones present.

        Additive by design: re-running it never removes an operator's own
        entries and never re-enables one they disabled. Returns how many
        rows were added.
        """
        from app.providers.embeddings.factory import EmbeddingProviderFactory
        from app.providers.llm.factory import LLMProviderFactory

        if overwrite:
            db.query(ProviderModel).delete()
            db.commit()

        existing = {
            (row.kind.value, row.provider, row.model_name) for row in db.execute(select(ProviderModel)).scalars()
        }

        added = 0
        sources = [
            (ModelKind.CHAT, LLMProviderFactory.list_providers()),
            (ModelKind.EMBEDDING, EmbeddingProviderFactory.list_providers()),
        ]
        for kind, providers in sources:
            for provider in providers:
                for order, model_name in enumerate(getattr(provider, "default_models", [])):
                    if (kind.value, provider.name, model_name) in existing:
                        continue
                    db.add(
                        ProviderModel(
                            kind=kind, provider=provider.name, model_name=model_name, sort_order=order
                        )
                    )
                    added += 1

        db.commit()
        invalidate()
        logger.info("Model catalogue seeded", extra=log_extra(added=added, overwrite=overwrite))
        return added

    def _require_known_provider(self, kind: str, provider: str) -> None:
        """A model must belong to a provider the application implements.

        Rows for an unknown provider would be silently unreachable - nothing
        would ever look them up - so this fails loudly instead.
        """
        from app.providers.embeddings.factory import EmbeddingProviderFactory
        from app.providers.llm.factory import LLMProviderFactory

        factory = LLMProviderFactory if kind == ModelKind.CHAT.value else EmbeddingProviderFactory
        known = {p.name for p in factory.list_providers()}
        if provider not in known:
            raise ValidationAppError(
                f"'{provider}' is not a known {kind} provider. Available: {', '.join(sorted(known))}."
            )


def get_model_catalog_service() -> ModelCatalogService:
    return ModelCatalogService()

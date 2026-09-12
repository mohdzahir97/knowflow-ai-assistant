"""Strategy interface every embedding provider must implement.

Kept entirely independent of `app/providers/llm` — the embedding
provider used to index a document has no relationship to the chat
provider used to answer questions about it.
"""
from abc import ABC, abstractmethod
from typing import ClassVar, List

from langchain_core.embeddings import Embeddings

from app.core.exceptions import EmbeddingError, InvalidModelError, MissingAPIKeyError
from app.providers.embeddings.caching import maybe_cache


class BaseEmbeddingProvider(ABC):
    name: ClassVar[str]
    display_name: ClassVar[str]

    # Seed data, not the source of truth - see `BaseChatProvider`.
    #
    # Changing an embedding model has a consequence a chat model does not:
    # documents are indexed into a collection keyed by provider and model,
    # so removing one from the catalogue makes documents indexed with it
    # unqueryable. Disable rather than delete unless the vectors are gone too.
    default_models: ClassVar[List[str]] = []

    @abstractmethod
    def _api_key(self) -> str:
        """Return the configured API key for this provider (empty if unset)."""

    def is_configured(self) -> bool:
        return bool(self._api_key())

    @property
    def supported_models(self) -> List[str]:
        from app.services.model_catalog import models_for

        return models_for("embedding", self.name, self.default_models)

    def validate_model(self, model: str) -> None:
        available = self.supported_models
        if model not in available:
            raise InvalidModelError(
                f"Model '{model}' is not supported by embedding provider '{self.name}'. "
                f"Supported models: {', '.join(available) or 'none configured'}."
            )

    @abstractmethod
    def _build(self, model: str) -> Embeddings:
        """Construct the concrete LangChain embeddings instance."""

    def get_embeddings(self, model: str) -> Embeddings:
        if not self.is_configured():
            raise MissingAPIKeyError(f"Embedding provider '{self.name}' is not configured on the server.")
        self.validate_model(model)
        try:
            # Wrapped here rather than at each call site so every consumer -
            # indexing, retrieval, the CRAG correction retries - shares one
            # query cache without having to know it exists.
            return maybe_cache(self._build(model), self.name, model)
        except MissingAPIKeyError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"Failed to initialize embedding provider '{self.name}': {exc}") from exc

    def to_metadata(self) -> dict:
        return {
            "provider": self.name,
            "display_name": self.display_name,
            "models": self.supported_models,
            "is_configured": self.is_configured(),
        }

"""Strategy interface every chat provider must implement.

Adding a new chat provider means creating one subclass and registering it
with `LLMProviderFactory` — no other file changes, no if/else chains.
"""
from abc import ABC, abstractmethod
from typing import ClassVar, List, Optional

from langchain_core.language_models import BaseChatModel

from app.core.config import get_settings
from app.core.exceptions import InvalidModelError, MissingAPIKeyError, ProviderError


class BaseChatProvider(ABC):
    name: ClassVar[str]
    display_name: ClassVar[str]

    # Seed data, not the source of truth. These are what a fresh
    # installation starts with; once the catalogue table has any row, the
    # database decides which models this provider offers. Edit models
    # through the admin API, not here.
    default_models: ClassVar[List[str]] = []

    @abstractmethod
    def _api_key(self) -> str:
        """Return the configured API key for this provider (empty if unset)."""

    def is_configured(self) -> bool:
        return bool(self._api_key())

    @property
    def supported_models(self) -> List[str]:
        """Models currently enabled for this provider.

        Read from the catalogue (cached in memory, refreshed when an
        administrator edits it), falling back to `default_models` only while
        the catalogue has never been seeded.
        """
        from app.services.model_catalog import models_for

        return models_for("chat", self.name, self.default_models)

    def validate_model(self, model: str) -> None:
        available = self.supported_models
        if model not in available:
            raise InvalidModelError(
                f"Model '{model}' is not supported by provider '{self.name}'. "
                f"Supported models: {', '.join(available) or 'none configured'}."
            )

    @abstractmethod
    def _build(self, model: str, temperature: float, max_tokens: int) -> BaseChatModel:
        """Construct the concrete LangChain chat model instance."""

    def get_chat_model(
        self,
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        if not self.is_configured():
            raise MissingAPIKeyError(f"Chat provider '{self.name}' is not configured on the server.")
        self.validate_model(model)
        settings = get_settings()
        try:
            return self._build(
                model,
                temperature if temperature is not None else settings.llm_temperature,
                max_tokens if max_tokens is not None else settings.llm_max_tokens,
            )
        except MissingAPIKeyError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to initialize chat provider '{self.name}': {exc}") from exc

    def to_metadata(self) -> dict:
        return {
            "provider": self.name,
            "display_name": self.display_name,
            "models": self.supported_models,
            "is_configured": self.is_configured(),
        }

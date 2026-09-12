"""Registry-based factory for embedding providers (mirrors LLMProviderFactory)."""
from typing import Dict, List, Type

from langchain_core.embeddings import Embeddings

from app.core.exceptions import InvalidProviderError
from app.providers.embeddings.base import BaseEmbeddingProvider


class EmbeddingProviderFactory:
    _registry: Dict[str, Type[BaseEmbeddingProvider]] = {}

    @classmethod
    def register(cls, name: str):
        def decorator(provider_cls: Type[BaseEmbeddingProvider]) -> Type[BaseEmbeddingProvider]:
            provider_cls.name = name
            cls._registry[name] = provider_cls
            return provider_cls

        return decorator

    @classmethod
    def get_provider(cls, name: str) -> BaseEmbeddingProvider:
        provider_cls = cls._registry.get(name)
        if provider_cls is None:
            raise InvalidProviderError(
                f"Embedding provider '{name}' is not supported. Supported providers: {', '.join(cls._registry)}."
            )
        return provider_cls()

    @classmethod
    def list_providers(cls) -> List[BaseEmbeddingProvider]:
        return [provider_cls() for provider_cls in cls._registry.values()]

    @classmethod
    def create_embeddings(cls, provider_name: str, model_name: str) -> Embeddings:
        provider = cls.get_provider(provider_name)
        return provider.get_embeddings(model_name)

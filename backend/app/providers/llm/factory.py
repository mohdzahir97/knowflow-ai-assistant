"""Registry-based factory for chat providers.

Providers self-register via the `@LLMProviderFactory.register(name)`
decorator on import, so the factory has zero knowledge of concrete
provider classes and no if/elif dispatch is ever needed.
"""
from typing import Dict, List, Optional, Type

from langchain_core.language_models import BaseChatModel

from app.core.exceptions import InvalidProviderError
from app.providers.llm.base import BaseChatProvider


class LLMProviderFactory:
    _registry: Dict[str, Type[BaseChatProvider]] = {}

    @classmethod
    def register(cls, name: str):
        def decorator(provider_cls: Type[BaseChatProvider]) -> Type[BaseChatProvider]:
            provider_cls.name = name
            cls._registry[name] = provider_cls
            return provider_cls

        return decorator

    @classmethod
    def get_provider(cls, name: str) -> BaseChatProvider:
        provider_cls = cls._registry.get(name)
        if provider_cls is None:
            raise InvalidProviderError(
                f"Chat provider '{name}' is not supported. Supported providers: {', '.join(cls._registry)}."
            )
        return provider_cls()

    @classmethod
    def list_providers(cls) -> List[BaseChatProvider]:
        return [provider_cls() for provider_cls in cls._registry.values()]

    @classmethod
    def create_chat_model(
        cls,
        provider_name: str,
        model_name: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        provider = cls.get_provider(provider_name)
        return provider.get_chat_model(model_name, temperature=temperature, max_tokens=max_tokens)

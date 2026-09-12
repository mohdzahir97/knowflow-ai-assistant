"""OpenAI chat provider."""
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.providers.llm.base import BaseChatProvider
from app.providers.llm.factory import LLMProviderFactory


@LLMProviderFactory.register("openai")
class OpenAIChatProvider(BaseChatProvider):
    display_name = "OpenAI"
    default_models = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]

    def _api_key(self) -> str:
        return get_settings().openai_api_key

    def _build(self, model: str, temperature: float, max_tokens: int) -> BaseChatModel:
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=self._api_key(),
            timeout=get_settings().llm_request_timeout_seconds,
        )

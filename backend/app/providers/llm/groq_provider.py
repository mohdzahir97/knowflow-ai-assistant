"""Groq chat provider."""
from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

from app.core.config import get_settings
from app.providers.llm.base import BaseChatProvider
from app.providers.llm.factory import LLMProviderFactory


@LLMProviderFactory.register("groq")
class GroqChatProvider(BaseChatProvider):
    display_name = "Groq"
    # mixtral-8x7b-32768 was deprecated 2025-03-20; llama-3.3-70b-versatile and
    # llama-3.1-8b-instant are scheduled for deprecation 2026-08-16. Using the
    # currently-recommended production models instead (console.groq.com/docs/models).
    default_models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]

    def _api_key(self) -> str:
        return get_settings().groq_api_key

    def _build(self, model: str, temperature: float, max_tokens: int) -> BaseChatModel:
        return ChatGroq(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=self._api_key(),
            timeout=get_settings().llm_request_timeout_seconds,
        )

"""Ollama chat provider (local models).

Ollama runs models locally and authenticates via a base URL rather than an
API key, so `is_configured()` is overridden to check the configured base
URL instead of the (absent) key. Model names correspond to Ollama "pull"
names; the user must have pulled the model into their Ollama instance
(e.g. `ollama pull llama3.1`) for it to actually work.
"""
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.core.config import get_settings
from app.providers.llm.base import BaseChatProvider
from app.providers.llm.factory import LLMProviderFactory


@LLMProviderFactory.register("ollama")
class OllamaChatProvider(BaseChatProvider):
    display_name = "Ollama (Local)"
    default_models = ["gemma4","llama3.1", "llama3.2", "qwen2.5", "gemma3", "mistral"]

    def _api_key(self) -> str:
        # Ollama does not use API keys; connection is via base URL.
        return ""

    def is_configured(self) -> bool:
        return bool(get_settings().ollama_base_url)

    def _build(self, model: str, temperature: float, max_tokens: int) -> BaseChatModel:
        return ChatOllama(
            model=model,
            temperature=temperature,
            num_predict=max_tokens,
            base_url=get_settings().ollama_base_url,
            # Without this, a single request to an unresponsive/stopped Ollama
            # server can hang indefinitely — this bounds each underlying HTTP
            # call rather than the whole chat turn (which may involve retries).
            client_kwargs={"timeout": get_settings().llm_request_timeout_seconds},
        )

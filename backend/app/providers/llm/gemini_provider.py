"""Google Gemini chat provider."""
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import get_settings
from app.providers.llm.base import BaseChatProvider
from app.providers.llm.factory import LLMProviderFactory


@LLMProviderFactory.register("gemini")
class GeminiChatProvider(BaseChatProvider):
    display_name = "Google Gemini"
    default_models = ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]

    def _api_key(self) -> str:
        return get_settings().google_api_key

    def _build(self, model: str, temperature: float, max_tokens: int) -> BaseChatModel:
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            max_output_tokens=max_tokens,
            google_api_key=self._api_key(),
            timeout=get_settings().llm_request_timeout_seconds,
        )

"""Google Gemini embedding provider."""
from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.core.config import get_settings
from app.providers.embeddings.base import BaseEmbeddingProvider
from app.providers.embeddings.factory import EmbeddingProviderFactory


@EmbeddingProviderFactory.register("gemini")
class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    display_name = "Google Gemini Embeddings"
    default_models = ["models/text-embedding-004", "models/embedding-001"]

    def _api_key(self) -> str:
        return get_settings().google_api_key

    def _build(self, model: str) -> Embeddings:
        return GoogleGenerativeAIEmbeddings(model=model, google_api_key=self._api_key())

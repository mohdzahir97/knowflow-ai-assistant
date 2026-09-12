"""OpenAI embedding provider."""
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings
from app.providers.embeddings.base import BaseEmbeddingProvider
from app.providers.embeddings.factory import EmbeddingProviderFactory


@EmbeddingProviderFactory.register("openai")
class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    display_name = "OpenAI Embeddings"
    default_models = ["text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"]

    def _api_key(self) -> str:
        return get_settings().openai_api_key

    def _build(self, model: str) -> Embeddings:
        return OpenAIEmbeddings(model=model, api_key=self._api_key())

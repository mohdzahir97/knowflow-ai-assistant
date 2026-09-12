"""Ollama embedding provider (local models).

Like the Ollama chat provider, this authenticates via a base URL rather
than an API key. Model names are Ollama "pull" names for embedding models
(e.g. `ollama pull nomic-embed-text`).
"""
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings

from app.core.config import get_settings
from app.providers.embeddings.base import BaseEmbeddingProvider
from app.providers.embeddings.factory import EmbeddingProviderFactory


@EmbeddingProviderFactory.register("ollama")
class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    display_name = "Ollama Embeddings (Local)"
    default_models = ["nomic-embed-text", "mxbai-embed-large", "bge-m3", "all-minilm"]

    def _api_key(self) -> str:
        # Ollama does not use API keys; connection is via base URL.
        return ""

    def is_configured(self) -> bool:
        return bool(get_settings().ollama_base_url)

    def _build(self, model: str) -> Embeddings:
        return OllamaEmbeddings(
            model=model,
            base_url=get_settings().ollama_base_url,
            # Bounds each individual embedding HTTP call. Without this, an
            # unresponsive/stopped Ollama server can hang a single chunk's
            # embed call indefinitely — and a document may have dozens of
            # chunks, each embedded with its own call.
            client_kwargs={"timeout": get_settings().llm_request_timeout_seconds},
        )

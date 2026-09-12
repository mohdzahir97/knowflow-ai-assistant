"""Importing this package registers all built-in embedding providers."""
from app.providers.embeddings.factory import EmbeddingProviderFactory
from app.providers.embeddings import (  # noqa: F401
    gemini_embeddings,
    ollama_embeddings,
    openai_embeddings,
)

__all__ = ["EmbeddingProviderFactory"]

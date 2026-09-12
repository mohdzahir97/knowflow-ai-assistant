import pytest

from app.core.exceptions import InvalidModelError, InvalidProviderError, MissingAPIKeyError
from app.providers.embeddings.factory import EmbeddingProviderFactory


def test_list_providers_includes_builtin_and_test_providers(register_fake_providers):
    names = {p.name for p in EmbeddingProviderFactory.list_providers()}
    assert {"openai", "gemini", "ollama", "testembed"}.issubset(names)


def test_get_provider_unknown_raises(register_fake_providers):
    with pytest.raises(InvalidProviderError):
        EmbeddingProviderFactory.get_provider("does-not-exist")


def test_create_embeddings_without_api_key_raises(register_fake_providers):
    with pytest.raises(MissingAPIKeyError):
        EmbeddingProviderFactory.create_embeddings("openai", "text-embedding-3-small")


def test_create_embeddings_invalid_model_raises(register_fake_providers):
    with pytest.raises(InvalidModelError):
        EmbeddingProviderFactory.create_embeddings("testembed", "not-a-real-model")


def test_create_embeddings_succeeds_and_produces_vectors(register_fake_providers):
    embeddings = EmbeddingProviderFactory.create_embeddings("testembed", "fake-embed-model")
    vector = embeddings.embed_query("hello world")
    assert isinstance(vector, list)
    assert len(vector) > 0


def test_ollama_is_configured_via_base_url_and_builds(register_fake_providers):
    """Ollama authenticates via base URL (not an API key), so it reports as
    configured and constructs without any key being set."""
    provider = EmbeddingProviderFactory.get_provider("ollama")
    assert provider.is_configured() is True
    embeddings = EmbeddingProviderFactory.create_embeddings("ollama", "nomic-embed-text")
    assert embeddings is not None

import pytest

from app.core.exceptions import InvalidModelError, InvalidProviderError, MissingAPIKeyError
from app.providers.llm.factory import LLMProviderFactory


def test_list_providers_includes_builtin_and_test_providers(register_fake_providers):
    names = {p.name for p in LLMProviderFactory.list_providers()}
    assert {"openai", "gemini", "groq", "ollama", "testchat"}.issubset(names)


def test_get_provider_unknown_raises(register_fake_providers):
    with pytest.raises(InvalidProviderError):
        LLMProviderFactory.get_provider("does-not-exist")


def test_create_chat_model_without_api_key_raises(register_fake_providers):
    with pytest.raises(MissingAPIKeyError):
        LLMProviderFactory.create_chat_model("openai", "gpt-4o-mini")


def test_create_chat_model_invalid_model_raises(register_fake_providers):
    with pytest.raises(InvalidModelError):
        LLMProviderFactory.create_chat_model("testchat", "not-a-real-model")


def test_create_chat_model_succeeds_for_configured_provider(register_fake_providers):
    model = LLMProviderFactory.create_chat_model("testchat", "fake-model")
    assert model is not None


def test_ollama_is_configured_via_base_url_and_builds(register_fake_providers):
    """Ollama authenticates via base URL (not an API key), so it reports as
    configured and constructs without any key being set."""
    provider = LLMProviderFactory.get_provider("ollama")
    assert provider.is_configured() is True
    model = LLMProviderFactory.create_chat_model("ollama", "llama3.1")
    assert model is not None


def test_runtime_switch_between_providers(register_fake_providers):
    """Switching providers is just a different factory call — no shared state, no restart."""
    first = LLMProviderFactory.create_chat_model("testchat", "fake-model")
    with pytest.raises(MissingAPIKeyError):
        LLMProviderFactory.create_chat_model("groq", "openai/gpt-oss-120b")
    assert first is not None

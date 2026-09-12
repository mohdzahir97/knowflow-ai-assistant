"""Tracing configuration and content redaction.

The redaction path is a data-protection control, not a convenience: with
tracing on, anything it fails to strip is transmitted to a third-party
service. These tests pin that behaviour.
"""
import pytest

from app.core import tracing
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _reset_tracing_cache():
    tracing.reset_tracing()
    yield
    tracing.reset_tracing()


def test_tracing_disabled_by_default(client):
    """Default posture must be off - opting in to sending data off-machine
    should always be explicit."""
    assert get_settings().langsmith_tracing is False
    assert tracing.get_tracing_client() is None


def test_tracing_without_api_key_degrades_to_disabled(monkeypatch):
    """A half-configured deployment must not crash, and must not attempt to
    send anywhere unauthenticated."""
    settings = get_settings()
    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "")
    assert tracing.get_tracing_client() is None


def test_redaction_strips_question_and_answer_text():
    payload = {
        "question": "What is our parental leave policy?",
        "answer": "Employees get 20 days.",
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "top_k": 4,
    }
    redacted = tracing._redact(payload)

    assert "parental leave" not in str(redacted)
    assert "20 days" not in str(redacted)
    # Non-sensitive operational metadata must survive, or traces are useless.
    assert redacted["provider"] == "groq"
    assert redacted["model"] == "openai/gpt-oss-120b"
    assert redacted["top_k"] == 4


def test_redaction_preserves_shape_for_debugging():
    """Redacted values should still say how much there was, so retrieval
    behaviour remains diagnosable without exposing content."""
    redacted = tracing._redact(
        {
            "question": "abcde",
            "chunks": ["chunk one", "chunk two", "chunk three"],
            "context": {"a": 1, "b": 2},
        }
    )
    assert "len=5" in redacted["question"]
    assert "3 items" in redacted["chunks"]
    assert "2 keys" in redacted["context"]


def test_redaction_covers_document_text_keys():
    """Retrieved document text arrives under several key names depending on
    where in the pipeline it is captured."""
    for key in ("page_content", "text", "documents", "messages", "prompt", "input", "output"):
        redacted = tracing._redact({key: "confidential handbook text"})
        assert "confidential" not in str(redacted), f"{key} leaked document text"


def test_traced_decorator_is_a_noop_when_disabled():
    """Application code is annotated unconditionally, so the decorator must
    be transparent - including preserving async behaviour - when off."""
    import asyncio

    @tracing.traced("unit.sync")
    def add(a, b):
        return a + b

    @tracing.traced("unit.async")
    async def add_async(a, b):
        return a + b

    assert add(2, 3) == 5
    assert asyncio.run(add_async(2, 3)) == 5

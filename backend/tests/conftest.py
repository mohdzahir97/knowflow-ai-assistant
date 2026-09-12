"""Shared pytest fixtures.

Env vars are set in `pytest_configure` — which runs before test modules
(and therefore `app.*`) are imported — since `Settings` is memoized via
`lru_cache` on first access and must never see real config/API keys.
"""
import os
import shutil
import uuid
from pathlib import Path
from typing import List

import pytest

TEST_DATA_DIR = Path(__file__).parent / "_test_data"


def pytest_configure(config) -> None:
    if TEST_DATA_DIR.exists():
        shutil.rmtree(TEST_DATA_DIR)
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

    os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_DATA_DIR / 'test.db').as_posix()}"
    os.environ["CHROMA_PERSIST_DIR"] = str(TEST_DATA_DIR / "chroma")
    os.environ["UPLOAD_DIR"] = str(TEST_DATA_DIR / "uploads")
    os.environ["LOG_DIR"] = str(TEST_DATA_DIR / "logs")
    os.environ["JWT_SECRET_KEY"] = "test-secret-key-not-for-production"
    os.environ["ENVIRONMENT"] = "test"

    # Rate limiting is enabled by default in production. The suite makes far
    # more requests per minute than any human would, so leave it off here and
    # let the dedicated rate-limit tests turn it on deliberately.
    os.environ["RATE_LIMIT_ENABLED"] = "false"

    # Force real provider keys empty regardless of what a developer's local
    # .env happens to contain, so "unconfigured provider" tests are hermetic
    # and never accidentally hit a real API.
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["GOOGLE_API_KEY"] = ""
    os.environ["GROQ_API_KEY"] = ""


@pytest.fixture(scope="session", autouse=True)
def register_fake_providers():
    """Registers deterministic fake chat/embedding providers through the
    real `LLMProviderFactory`/`EmbeddingProviderFactory` registries, so
    tests exercise production code paths without real API keys or network
    calls, and without needing to mock application internals.
    """
    import hashlib
    import math

    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from app.providers.embeddings.base import BaseEmbeddingProvider
    from app.providers.embeddings.factory import EmbeddingProviderFactory
    from app.providers.llm.base import BaseChatProvider
    from app.providers.llm.factory import LLMProviderFactory

    class FakeEmbeddings(Embeddings):
        """Deterministic, unit-normalised fake embeddings.

        Normalisation matters: real embedding models emit unit vectors, and
        Chroma derives its 0-1 relevance score assuming that. Unnormalised
        vectors produce out-of-range (even negative) relevance, which would
        make every result grade as poor context and exercise a code path
        production never takes.
        """

        def _vec(self, text: str) -> List[float]:
            digest = hashlib.sha256(text.encode()).digest()
            raw = [b / 255.0 for b in digest[:16]]
            magnitude = math.sqrt(sum(v * v for v in raw)) or 1.0
            return [v / magnitude for v in raw]

        def embed_documents(self, texts: List[str]) -> List[List[float]]:
            return [self._vec(t) for t in texts]

        def embed_query(self, text: str) -> List[float]:
            return self._vec(text)

    @EmbeddingProviderFactory.register("testembed")
    class TestEmbeddingProvider(BaseEmbeddingProvider):
        display_name = "Test Embeddings"
        default_models = ["fake-embed-model"]

        def _api_key(self) -> str:
            return "fake-key"

        def _build(self, model: str) -> Embeddings:
            return FakeEmbeddings()

    class FakeChatModel(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
            question_line = messages[-1].content.lower().split("question:")[-1]
            if "paid leave" in question_line:
                text = "Employees get 20 days of paid leave per year. [sample.pdf, Page 1]"
            else:
                text = "I couldn't find that information in the uploaded documents."
            message = AIMessage(
                content=text, usage_metadata={"input_tokens": 42, "output_tokens": 8, "total_tokens": 50}
            )
            return ChatResult(generations=[ChatGeneration(message=message)])

        @property
        def _llm_type(self) -> str:
            return "fake"

    @LLMProviderFactory.register("testchat")
    class TestChatProvider(BaseChatProvider):
        display_name = "Test Chat"
        default_models = ["fake-model"]

        def _api_key(self) -> str:
            return "fake-key"

        def _build(self, model: str, temperature: float, max_tokens: int) -> BaseChatModel:
            return FakeChatModel()


@pytest.fixture(scope="session")
def client(register_fake_providers):
    from fastapi.testclient import TestClient

    import app.db.models  # noqa: F401 -- register all models on Base.metadata
    from app.db.base import Base
    from app.db.session import engine
    from app.main import app

    Base.metadata.create_all(bind=engine)

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_knowledge_base(request):
    """Empty the shared knowledge base before each test.

    When documents were private to each uploader, a test that created a fresh
    user got a clean corpus for free. The knowledge base is now shared, so
    documents persist across tests within a session and would otherwise leak
    into each other's assertions. This restores the isolation explicitly.

    Skipped for tests that never touch the app, so unit tests stay fast.
    """
    if "client" not in request.fixturenames:
        yield
        return

    request.getfixturevalue("client")

    def _empty() -> None:
        import chromadb

        from app.core.config import get_settings
        from app.db.models.document import Document
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.query(Document).delete()
            db.commit()

        chroma_client = chromadb.PersistentClient(path=str(get_settings().chroma_path))
        for collection in chroma_client.list_collections():
            chroma_client.delete_collection(collection.name)

    _empty()
    yield


def _register_and_login(client, email: str, password: str = "password123") -> dict:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text

    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text

    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


@pytest.fixture
def auth_headers(client):
    """An ordinary end user - the default role for anyone who signs up.

    Deliberately NOT an admin: self-signup must never grant knowledge-base
    management rights, and most tests should run as the least-privileged
    role so a missing authorization check shows up as a failure.
    """
    return _register_and_login(client, f"user-{uuid.uuid4().hex[:12]}@example.com")


@pytest.fixture
def admin_headers(client):
    """An administrator, for knowledge-base management.

    The role is set directly in the database rather than through an API,
    because there deliberately is no endpoint that lets an account promote
    itself - that would defeat the whole control.
    """
    from app.db.models.user import User, UserRole
    from app.db.session import SessionLocal

    email = f"admin-{uuid.uuid4().hex[:12]}@example.com"
    headers = _register_and_login(client, email)

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        user.role = UserRole.ADMIN
        db.commit()

    return headers


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    return (Path(__file__).parent / "fixtures" / "sample.pdf").read_bytes()

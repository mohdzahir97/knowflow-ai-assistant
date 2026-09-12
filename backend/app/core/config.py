"""Centralized application configuration.

All environment-driven settings are defined here. No other module should
read `os.environ` directly — inject `Settings` via `get_settings()` instead.
"""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "AI Company Knowledge Assistant"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS
    # Both clients ship in this repo and may run side by side: Streamlit on
    # 8501, the React dev server on 5173, and its preview build on 4173.
    cors_origins: List[str] = [
        "http://localhost:8501",  # Streamlit client
        "http://localhost:5173",  # React dev server
        "http://localhost:4173",  # React `vite preview`
        "http://localhost:5174",  # React container (docker compose --profile react)
    ]

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # JWT
    jwt_secret_key: str = "change-this-to-a-random-secret-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_minutes: int = 10080

    # LLM Providers
    openai_api_key: str = ""
    google_api_key: str = ""
    groq_api_key: str = ""

    # Ollama runs locally and uses a base URL instead of an API key.
    ollama_base_url: str = "http://localhost:11434"

    default_chat_provider: str = "openai"
    default_chat_model: str = "gpt-4o-mini"
    default_embedding_provider: str = "openai"
    default_embedding_model: str = "text-embedding-3-small"

    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024
    llm_request_timeout_seconds: int = 60

    # ---------------------------------------------------------------
    # Observability (LangSmith)
    # ---------------------------------------------------------------
    # LangSmith is a hosted service: enabling tracing sends run data to
    # LangChain's servers. Because this application indexes private company
    # documents, `langsmith_redact_content` defaults to True and strips
    # question text, document text and answers before anything leaves the
    # process — timings, token counts, providers and structure still go.
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "ai-company-knowledge-assistant"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_redact_content: bool = True

    # RAG
    chunk_size: int = 1000
    chunk_overlap: int = 150
    retrieval_top_k: int = 4

    # ---------------------------------------------------------------
    # Rate limiting
    # ---------------------------------------------------------------
    # Counters are in-process, so with multiple workers the effective limit
    # is multiplied by worker count. Move to Redis before scaling out.
    rate_limit_enabled: bool = True
    rate_limit_chat_per_minute: int = 20
    rate_limit_auth_per_minute: int = 10
    rate_limit_upload_per_hour: int = 50

    # ---------------------------------------------------------------
    # AI guardrails
    # ---------------------------------------------------------------
    # Pattern-based, not model-based: an ML classifier or LLM judge would
    # catch more but adds either heavy dependencies or a model call to every
    # request. These are one layer; the structural protections in
    # prompt_builder are what actually contain a malicious document.
    guardrails_enabled: bool = True
    guardrail_max_question_chars: int = 2000
    # Redact identifiers out of the query before it is embedded or sent to a
    # provider, so they do not leave this process.
    guardrail_redact_pii_in_queries: bool = True
    # Redact identifiers out of answers. An answer can only contain PII that
    # was already in a document, but showing it in chat widens who sees it.
    guardrail_redact_pii_in_answers: bool = True

    # Hybrid retrieval fuses vector similarity with BM25 keyword matching.
    # Vector search alone misses exact-phrase queries: a heading mentioned in
    # a table of contents can outrank the section that actually contains the
    # text, because both are topically similar. Keyword search does not share
    # that failure mode.
    hybrid_search_enabled: bool = True
    # Reciprocal Rank Fusion constant. 60 is the value from the original RRF
    # paper and is the usual default; larger values flatten the weighting
    # between the two result lists.
    hybrid_rrf_k: int = 60

    # ---------------------------------------------------------------
    # Corrective RAG
    # ---------------------------------------------------------------
    # Grading is score-based rather than LLM-based: Chroma returns
    # normalised 0-1 relevance scores with the results, so judging context
    # quality costs nothing extra. Measured on this corpus, an on-topic
    # query scores ~0.34 and an off-topic one ~0.10, so 0.25 separates them
    # with margin. Tune per corpus - embedding models differ in scale.
    crag_enabled: bool = True
    crag_relevance_threshold: float = 0.25
    # How many chunks must clear the threshold for context to count as good.
    crag_min_relevant_chunks: int = 1
    # Bounded so a bad query can never loop: each attempt is one LLM rewrite
    # plus one retrieval.
    crag_max_correction_attempts: int = 1
    # Verifying the answer is grounded costs one additional LLM call per
    # answered question (skipped when the assistant declines to answer).
    # Off by default because that roughly doubles latency on local models.
    crag_verify_groundedness: bool = False

    # OCR fallback for scanned / image-only PDFs (no native text layer).
    # Uses RapidOCR (ONNX) — no system binary required.
    ocr_enabled: bool = True
    ocr_dpi: int = 200

    # Storage
    upload_dir: str = "./data/uploads"
    chroma_persist_dir: str = "./data/chroma"
    max_upload_size_mb: int = 25
    # Ceiling for the whole request body (covers multi-file uploads); rejected
    # before multipart parsing begins, so it never depends on max_upload_size_mb.
    max_request_body_mb: int = 100

    # Email and account recovery
    # "console" logs the message (development default, nothing to sign up
    # for); "smtp" delivers via the SMTP settings below. No third-party
    # email service is integrated.
    email_backend: str = "console"
    email_from: str = "no-reply@example.com"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False

    # Where the emailed links point - the frontend, not the API.
    frontend_base_url: str = "http://localhost:8501"
    password_reset_token_expire_minutes: int = 60
    email_verification_token_expire_minutes: int = 1440
    # Off by default so enabling verification later never locks out accounts
    # created before it existed.
    require_email_verification: bool = False

    # Caching
    # Embedding a question is the slowest step before an answer can start and
    # is a pure function of (provider, model, text), so repeat questions are
    # served from memory. Disable only when profiling cold-path latency.
    embedding_cache_enabled: bool = True

    # Security headers
    security_headers_enabled: bool = True
    # Only ever sent over HTTPS. One year, the value browsers require for
    # preload eligibility.
    hsts_max_age_seconds: int = 31536000

    # Logging
    log_level: str = "INFO"
    log_dir: str = "./logs"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def chroma_path(self) -> Path:
        path = Path(self.chroma_persist_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_path(self) -> Path:
        path = Path(self.log_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def database_path_dir(self) -> Path:
        if self.database_url.startswith("sqlite"):
            db_file = self.database_url.split("///")[-1]
            path = Path(db_file).parent
            path.mkdir(parents=True, exist_ok=True)
            return path
        return Path(".")


@lru_cache
def get_settings() -> Settings:
    """Return a cached, process-wide Settings instance."""
    return Settings()

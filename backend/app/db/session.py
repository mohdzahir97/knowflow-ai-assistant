"""SQLAlchemy engine/session management and the FastAPI DB dependency."""
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

# Ensure the SQLite directory exists before the engine tries to open the file.
settings.database_path_dir

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, connection_record) -> None:
        """Apply per-connection SQLite pragmas.

        journal_mode=WAL  — SQLite allows only one writer at a time. In
            rollback-journal mode a writer also blocks readers, so a
            background indexing worker writing to the same file would stall
            the API. WAL lets readers proceed concurrently with a writer,
            which is what makes a separate worker process viable at all.
            WAL is persistent (a database property, not a connection one),
            but setting it per-connect is harmless and self-healing.
        busy_timeout    — without it a concurrent writer fails instantly with
            "database is locked"; with it SQLite waits and retries.
        foreign_keys=ON — SQLite ignores FK constraints unless explicitly
            enabled, so the ON DELETE CASCADE rules in our schema were
            previously enforced only by the ORM. This makes them real at the
            database level too.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

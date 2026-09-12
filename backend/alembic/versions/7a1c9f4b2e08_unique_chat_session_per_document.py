"""unique chat session per (user, document)

Enforces the "at most one document-scoped chat session per user per
document" invariant at the database level. Previously this was only
checked with a SELECT-then-INSERT in ChatService, which two concurrent
requests could both pass, producing duplicate sessions and silently
splitting a document's chat history in two.

General (non-document) sessions keep document_id = NULL. SQLite and
Postgres both treat NULLs as distinct in a unique index, so a user can
still have any number of general sessions.

Revision ID: 7a1c9f4b2e08
Revises: 5e2644346d5e
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7a1c9f4b2e08"
down_revision: Union[str, None] = "5e2644346d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_chat_sessions_user_document"


def upgrade() -> None:
    # Collapse any duplicates created before the constraint existed, otherwise
    # index creation fails on live data. Keep the oldest session of each pair
    # (it holds the earliest history) and re-point the newer sessions'
    # messages at it, so no messages are lost.
    connection = op.get_bind()

    duplicate_groups = connection.execute(
        sa.text(
            """
            SELECT user_id, document_id, MIN(created_at) AS keep_created
            FROM chat_sessions
            WHERE document_id IS NOT NULL
            GROUP BY user_id, document_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    for user_id, document_id, _ in duplicate_groups:
        sessions = connection.execute(
            sa.text(
                """
                SELECT id FROM chat_sessions
                WHERE user_id = :user_id AND document_id = :document_id
                ORDER BY created_at ASC
                """
            ),
            {"user_id": user_id, "document_id": document_id},
        ).fetchall()

        keep_id = sessions[0][0]
        for (duplicate_id,) in sessions[1:]:
            connection.execute(
                sa.text("UPDATE chat_messages SET session_id = :keep WHERE session_id = :dup"),
                {"keep": keep_id, "dup": duplicate_id},
            )
            connection.execute(
                sa.text("DELETE FROM chat_sessions WHERE id = :dup"),
                {"dup": duplicate_id},
            )

    op.create_index(_INDEX_NAME, "chat_sessions", ["user_id", "document_id"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="chat_sessions")

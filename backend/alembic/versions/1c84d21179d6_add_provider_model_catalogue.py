"""add provider model catalogue

Revision ID: 1c84d21179d6
Revises: e5b0618cfdff
Create Date: 2026-08-12

Creates `provider_models` and seeds it with the model line-up that was
previously hardcoded in the provider classes, so an existing installation
keeps offering exactly the same models across this upgrade.

The seed list is written out literally rather than imported from
`app.providers`. A migration must produce the same result whenever it runs;
importing today's code would make this migration's outcome change every time
someone edits a provider, and replaying history would no longer reproduce
history. This list is a snapshot of 2026-08-12 and is meant to go stale -
after this point the catalogue is edited through the admin API.

The proposed rewrite of `uq_chat_sessions_user_document` has been dropped; it
is a SQLite reflection artifact, not a real change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1c84d21179d6'
down_revision: Union[str, None] = 'e5b0618cfdff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (kind, provider, [models in display order])
_SEED = [
    ("chat", "openai", ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]),
    ("chat", "gemini", ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]),
    ("chat", "groq", ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]),
    ("chat", "ollama", ["gemma4", "llama3.1", "llama3.2", "qwen2.5", "gemma3", "mistral"]),
    ("embedding", "openai", ["text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"]),
    ("embedding", "gemini", ["models/text-embedding-004", "models/embedding-001"]),
    ("embedding", "ollama", ["nomic-embed-text", "mxbai-embed-large", "bge-m3", "all-minilm"]),
]


def upgrade() -> None:
    provider_models = op.create_table(
        'provider_models',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('kind', sa.Enum('CHAT', 'EMBEDDING', name='modelkind'), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('model_name', sa.String(length=200), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'provider', 'model_name', name='uq_provider_models_identity'),
    )
    op.create_index(op.f('ix_provider_models_kind'), 'provider_models', ['kind'], unique=False)
    op.create_index(op.f('ix_provider_models_provider'), 'provider_models', ['provider'], unique=False)

    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    rows = []
    for kind, provider, models in _SEED:
        for order, model_name in enumerate(models):
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    # The Enum column stores the member *name*, not its value.
                    "kind": kind.upper(),
                    "provider": provider,
                    "model_name": model_name,
                    "display_name": None,
                    "is_enabled": True,
                    "sort_order": order,
                    "created_at": now,
                    "updated_at": now,
                }
            )
    op.bulk_insert(provider_models, rows)


def downgrade() -> None:
    op.drop_index(op.f('ix_provider_models_provider'), table_name='provider_models')
    op.drop_index(op.f('ix_provider_models_kind'), table_name='provider_models')
    op.drop_table('provider_models')

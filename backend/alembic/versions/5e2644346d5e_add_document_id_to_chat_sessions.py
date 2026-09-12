"""add document_id to chat_sessions

Revision ID: 5e2644346d5e
Revises: ecd1220741fd
Create Date: 2026-07-08 16:17:08.248287

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5e2644346d5e'
down_revision: Union[str, None] = 'ecd1220741fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite cannot ALTER a table to add a foreign key constraint in place;
    # batch mode recreates the table with the new schema instead.
    with op.batch_alter_table('chat_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('document_id', sa.String(), nullable=True))
        batch_op.create_index(batch_op.f('ix_chat_sessions_document_id'), ['document_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_chat_sessions_document_id_documents', 'documents', ['document_id'], ['id'], ondelete='CASCADE'
        )


def downgrade() -> None:
    with op.batch_alter_table('chat_sessions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_chat_sessions_document_id_documents', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_chat_sessions_document_id'))
        batch_op.drop_column('document_id')

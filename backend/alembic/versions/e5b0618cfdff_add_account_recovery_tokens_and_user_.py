"""add account recovery tokens and user verification

Revision ID: e5b0618cfdff
Revises: 916f929525a4
Create Date: 2026-08-11 17:18:10.648269

Adds the single-use token table behind password reset and email
verification, plus two columns on users.

`is_verified` is added NOT NULL **with a server default**. Autogenerate
omitted the default, which would fail outright on any installation that
already has accounts - there is no value to put in the existing rows. The
default backfills them as unverified, which is the correct starting state:
those accounts have never confirmed their address.

`session_epoch` defaults to 0 for every existing row, which matches the
default claim on tokens already in circulation - so nobody is signed out by
this migration. It is incremented only when a password is reset.

The proposed rewrite of `uq_chat_sessions_user_document` has been dropped -
it is a reflection artifact on SQLite, not a real change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5b0618cfdff'
down_revision: Union[str, None] = '916f929525a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'auth_tokens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column(
            'purpose',
            sa.Enum('PASSWORD_RESET', 'EMAIL_VERIFICATION', name='tokenpurpose'),
            nullable=False,
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_auth_tokens_purpose'), 'auth_tokens', ['purpose'], unique=False)
    op.create_index(op.f('ix_auth_tokens_token_hash'), 'auth_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_auth_tokens_user_id'), 'auth_tokens', ['user_id'], unique=False)

    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column('session_epoch', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('session_epoch')
        batch_op.drop_column('is_verified')

    op.drop_index(op.f('ix_auth_tokens_user_id'), table_name='auth_tokens')
    op.drop_index(op.f('ix_auth_tokens_token_hash'), table_name='auth_tokens')
    op.drop_index(op.f('ix_auth_tokens_purpose'), table_name='auth_tokens')
    op.drop_table('auth_tokens')

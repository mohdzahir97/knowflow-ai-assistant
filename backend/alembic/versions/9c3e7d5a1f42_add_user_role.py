"""add user role (ADMIN / USER)

Introduces role-based access control. The knowledge base becomes a single
shared corpus curated by admins, so document management must be restricted
server-side; this column is what those checks read.

Backfill policy: existing accounts that have uploaded documents are the de
facto knowledge-base curators, so they are promoted to ADMIN. If no account
has uploaded anything, the oldest account is promoted, guaranteeing that an
already-deployed instance never ends up with zero admins and an
unmanageable knowledge base. Everyone else becomes USER.

Revision ID: 9c3e7d5a1f42
Revises: 7a1c9f4b2e08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9c3e7d5a1f42"
down_revision: Union[str, None] = "7a1c9f4b2e08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Added nullable first, then backfilled, then made non-nullable: adding a
    # NOT NULL column to a populated table fails otherwise.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("role", sa.Enum("ADMIN", "USER", name="userrole"), nullable=True))

    connection = op.get_bind()
    connection.execute(sa.text("UPDATE users SET role = 'USER'"))

    promoted = connection.execute(
        sa.text("UPDATE users SET role = 'ADMIN' WHERE id IN (SELECT DISTINCT user_id FROM documents)")
    ).rowcount

    if not promoted:
        # No documents anywhere: promote the oldest account so the instance
        # still has someone who can manage the knowledge base.
        oldest = connection.execute(sa.text("SELECT id FROM users ORDER BY created_at ASC LIMIT 1")).fetchone()
        if oldest:
            connection.execute(sa.text("UPDATE users SET role = 'ADMIN' WHERE id = :id"), {"id": oldest[0]})

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("role", existing_type=sa.Enum("ADMIN", "USER", name="userrole"), nullable=False)
        batch_op.create_index(batch_op.f("ix_users_role"), ["role"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_role"))
        batch_op.drop_column("role")

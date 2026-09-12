"""add projects and chat project_id

Introduces user-owned projects for grouping chats, and an optional
`project_id` on chat sessions.

Two deliberate choices:

* The foreign key uses ON DELETE SET NULL. Deleting a project is an
  organisational action; it must detach its chats, never destroy them.

* The existing `uq_chat_sessions_user_document` unique index is left
  untouched. Autogenerate proposed dropping and recreating it as a UNIQUE
  constraint, but the two are functionally identical here, and briefly
  dropping the guarantee that prevents duplicate document sessions is real
  risk for a cosmetic change.

Revision ID: 8cc2b158582a
Revises: 9c3e7d5a1f42
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8cc2b158582a"
down_revision: Union[str, None] = "9c3e7d5a1f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_NAME = "fk_chat_sessions_project_id_projects"
_INDEX_NAME = "ix_chat_sessions_project_id"


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
    )
    op.create_index(op.f("ix_projects_user_id"), "projects", ["user_id"], unique=False)

    # SQLite cannot ALTER a table to add a foreign key; batch mode recreates
    # it with the new schema instead.
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(), nullable=True))
        batch_op.create_index(_INDEX_NAME, ["project_id"], unique=False)
        batch_op.create_foreign_key(_FK_NAME, "projects", ["project_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
        batch_op.drop_index(_INDEX_NAME)
        batch_op.drop_column("project_id")

    op.drop_index(op.f("ix_projects_user_id"), table_name="projects")
    op.drop_table("projects")

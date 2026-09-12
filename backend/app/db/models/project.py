"""Project model - a user-owned folder for grouping chats.

Deliberately flat: a project holds chats, and that is all. No nesting, no
sub-projects, no sharing. Users organising their own conversations do not
need a hierarchy, and a tree would bring reparenting, cycle prevention and
recursive authorization for no benefit here.

A chat may belong to one project or to none; "no project" is represented by
a null `project_id` on ChatSession rather than by a synthetic "General"
project, so there is no row that must exist for the app to work.
"""
from typing import TYPE_CHECKING, List

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.chat import ChatSession
    from app.db.models.user import User


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        # Duplicate names within one user's workspace are confusing rather
        # than harmful, but preventing them is cheap. Scoped to the user, so
        # two people may both have a project called "Banking".
        UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    owner: Mapped["User"] = relationship(back_populates="projects")
    # Deleting a project must not delete the conversations inside it - that
    # would make an organisational action destructive. Chats are detached
    # instead (project_id set to null) and remain in the user's history.
    chats: Mapped[List["ChatSession"]] = relationship(back_populates="project")

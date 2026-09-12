"""Projects and chat organisation.

Every method takes the acting user and filters by ownership. That is the
point: a caller must never be able to reach another user's project or chat
by supplying its id. Missing and not-yours both raise ResourceNotFoundError
rather than a distinguishable "forbidden", so an attacker cannot use the
error to confirm that an id exists.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundError, ValidationAppError
from app.core.logging import get_logger, log_extra
from app.db.models.chat import ChatMessage, ChatSession
from app.db.models.project import Project
from app.db.models.user import User

logger = get_logger("app.projects")


class ProjectService:
    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def create(self, db: Session, user: User, name: str) -> Project:
        project = Project(user_id=user.id, name=name)
        db.add(project)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ValidationAppError(f"You already have a project named '{name}'.")
        db.refresh(project)
        logger.info("Project created", extra=log_extra(user_id=user.id, project_id=project.id))
        return project

    def list_projects(self, db: Session, user: User) -> List[tuple[Project, int]]:
        """Projects with their chat counts, newest first.

        Counted in SQL rather than by loading each project's chats, so the
        sidebar costs one query regardless of how many chats exist.
        """
        rows = db.execute(
            select(Project, func.count(ChatSession.id))
            .outerjoin(ChatSession, ChatSession.project_id == Project.id)
            .where(Project.user_id == user.id)
            .group_by(Project.id)
            .order_by(Project.created_at.desc())
        ).all()
        return [(project, count) for project, count in rows]

    def get(self, db: Session, user: User, project_id: str) -> Project:
        project = db.get(Project, project_id)
        if not project or project.user_id != user.id:
            raise ResourceNotFoundError("Project not found.")
        return project

    def rename(self, db: Session, user: User, project_id: str, name: str) -> Project:
        project = self.get(db, user, project_id)
        project.name = name
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ValidationAppError(f"You already have a project named '{name}'.")
        db.refresh(project)
        return project

    def delete(self, db: Session, user: User, project_id: str) -> int:
        """Delete a project, detaching its chats rather than deleting them.

        Returns how many chats were detached. Losing conversations because a
        folder was removed would be a destructive surprise, so they simply
        return to the ungrouped list.
        """
        project = self.get(db, user, project_id)
        detached = (
            db.query(ChatSession)
            .filter(ChatSession.project_id == project.id)
            .update({ChatSession.project_id: None}, synchronize_session=False)
        )
        db.delete(project)
        db.commit()
        logger.info(
            "Project deleted", extra=log_extra(user_id=user.id, project_id=project_id, detached_chats=detached)
        )
        return detached

    # ------------------------------------------------------------------
    # Chat organisation
    # ------------------------------------------------------------------

    def _owned_chat(self, db: Session, user: User, chat_id: str) -> ChatSession:
        chat = db.get(ChatSession, chat_id)
        if not chat or chat.user_id != user.id:
            raise ResourceNotFoundError("Chat not found.")
        return chat

    def rename_chat(self, db: Session, user: User, chat_id: str, title: str) -> ChatSession:
        chat = self._owned_chat(db, user, chat_id)
        chat.title = title
        db.commit()
        db.refresh(chat)
        return chat

    def move_chat(self, db: Session, user: User, chat_id: str, project_id: Optional[str]) -> ChatSession:
        """Put a chat into a project, or take it out when project_id is None."""
        chat = self._owned_chat(db, user, chat_id)
        if project_id is not None:
            # Validates ownership of the destination too - a chat must never
            # be moved into someone else's project.
            self.get(db, user, project_id)
        chat.project_id = project_id
        db.commit()
        db.refresh(chat)
        return chat

    def list_chats(
        self, db: Session, user: User, project_id: Optional[str] = None, ungrouped_only: bool = False
    ) -> List[tuple[ChatSession, int]]:
        """A user's chats with message counts, most recently updated first.

        Document-scoped sessions are excluded: those are the admin's
        document-testing conversations, not part of anyone's chat history.
        """
        query = (
            select(ChatSession, func.count(ChatMessage.id))
            .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.user_id == user.id, ChatSession.document_id.is_(None))
            .group_by(ChatSession.id)
            .order_by(ChatSession.updated_at.desc())
        )
        if ungrouped_only:
            query = query.where(ChatSession.project_id.is_(None))
        elif project_id is not None:
            self.get(db, user, project_id)
            query = query.where(ChatSession.project_id == project_id)

        return [(chat, count) for chat, count in db.execute(query).all()]

    def search_chats(self, db: Session, user: User, query_text: str) -> List[tuple[ChatSession, int]]:
        """Find a user's chats by title or message content.

        Scoped to the acting user in the WHERE clause, so search can never
        surface another user's conversation.
        """
        term = f"%{query_text.strip()}%"
        if not query_text.strip():
            return []

        matching_session_ids = select(ChatMessage.session_id).where(ChatMessage.content.ilike(term))

        rows = db.execute(
            select(ChatSession, func.count(ChatMessage.id))
            .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatSession.user_id == user.id,
                ChatSession.document_id.is_(None),
                or_(ChatSession.title.ilike(term), ChatSession.id.in_(matching_session_ids)),
            )
            .group_by(ChatSession.id)
            .order_by(ChatSession.updated_at.desc())
        ).all()
        return [(chat, count) for chat, count in rows]


def get_project_service() -> ProjectService:
    return ProjectService()

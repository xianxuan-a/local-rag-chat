"""Data-access operations for knowledge bases."""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import ChatSession, FileRecord, KnowledgeBase


class KnowledgeBaseRepository:
    """Persist knowledge bases without owning transaction boundaries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        name: str | KnowledgeBase,
        description: str | None = None,
    ) -> KnowledgeBase:
        knowledge_base = (
            name
            if isinstance(name, KnowledgeBase)
            else KnowledgeBase(name=name, description=description)
        )
        self.db.add(knowledge_base)
        self.db.flush()
        self.db.refresh(knowledge_base)
        return knowledge_base

    def get_by_id(self, knowledge_base_id: str) -> KnowledgeBase | None:
        statement = select(KnowledgeBase).where(
            KnowledgeBase.id == str(knowledge_base_id)
        )
        return self.db.scalar(statement)

    def get_by_name(self, name: str) -> KnowledgeBase | None:
        statement = select(KnowledgeBase).where(KnowledgeBase.name == name)
        return self.db.scalar(statement)

    def list_all(self) -> list[KnowledgeBase]:
        statement = select(KnowledgeBase).order_by(
            KnowledgeBase.created_at.asc(), KnowledgeBase.id.asc()
        )
        return list(self.db.scalars(statement).all())

    def has_files(self, knowledge_base_id: str) -> bool:
        statement = select(
            exists().where(FileRecord.knowledge_base_id == str(knowledge_base_id))
        )
        return bool(self.db.scalar(statement))

    def has_sessions(self, knowledge_base_id: str) -> bool:
        statement = select(
            exists().where(ChatSession.knowledge_base_id == str(knowledge_base_id))
        )
        return bool(self.db.scalar(statement))

    def has_dependencies(self, knowledge_base_id: str) -> bool:
        """Return whether deletion must be rejected by the service layer."""

        return self.has_files(knowledge_base_id) or self.has_sessions(
            knowledge_base_id
        )

    def delete(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        self.db.delete(knowledge_base)
        self.db.flush()
        return knowledge_base

"""Knowledge-base business operations and transaction boundaries."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ResourceNotFoundException
from app.models.knowledge_base import KnowledgeBase
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.schemas.knowledge_base import KnowledgeBaseCreate


class KnowledgeBaseService:
    """Provide real CRUD behavior for knowledge bases."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = KnowledgeBaseRepository(db)

    def create_knowledge_base(self, payload: KnowledgeBaseCreate) -> KnowledgeBase:
        """Create and commit one knowledge base."""
        try:
            knowledge_base = self.repository.create(
                name=payload.name,
                description=payload.description,
            )
            self.db.commit()
            return knowledge_base
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictException("同名知识库已存在") from exc
        except Exception:
            self.db.rollback()
            raise

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        """Return all knowledge bases in repository-defined order."""
        return self.repository.list_all()

    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        """Return one knowledge base or a safe 404 error."""
        knowledge_base = self.repository.get_by_id(knowledge_base_id)
        if knowledge_base is None:
            self.db.rollback()
            raise ResourceNotFoundException("知识库不存在")
        return knowledge_base

    def delete_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        """Delete an empty knowledge base and reject dependent records."""
        knowledge_base = self.repository.get_by_id(knowledge_base_id)
        if knowledge_base is None:
            self.db.rollback()
            raise ResourceNotFoundException("知识库不存在")
        if self.repository.has_dependencies(knowledge_base_id):
            self.db.rollback()
            raise ConflictException("知识库包含文件或会话，不能删除")

        try:
            self.repository.delete(knowledge_base)
            self.db.commit()
            return knowledge_base
        except Exception:
            self.db.rollback()
            raise

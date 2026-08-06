"""Data-access operations for knowledge bases."""

from __future__ import annotations

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.models import ChatSession, FileRecord, KnowledgeBase
from app.core.retrieval_modes import KnowledgeBaseWebPolicy


class KnowledgeBaseRepository:
    """Persist knowledge bases without owning transaction boundaries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        name: str | KnowledgeBase,
        description: str | None = None,
        owner_id: str | None = None,
        web_access_policy: KnowledgeBaseWebPolicy | str = (
            KnowledgeBaseWebPolicy.INHERIT
        ),
    ) -> KnowledgeBase:
        knowledge_base = (
            name
            if isinstance(name, KnowledgeBase)
            else KnowledgeBase(
                name=name,
                description=description,
                owner_id=owner_id,
                web_access_policy=(
                    web_access_policy.value
                    if isinstance(
                        web_access_policy,
                        KnowledgeBaseWebPolicy,
                    )
                    else str(web_access_policy)
                ),
            )
        )
        self.db.add(knowledge_base)
        self.db.flush()
        self.db.refresh(knowledge_base)
        return knowledge_base

    def get_by_id(
        self, knowledge_base_id: str, owner_id: str | None = None
    ) -> KnowledgeBase | None:
        statement = select(KnowledgeBase).where(
            KnowledgeBase.id == str(knowledge_base_id)
        )
        if owner_id is not None:
            statement = statement.where(KnowledgeBase.owner_id == owner_id)
        return self.db.scalar(statement)

    def get_by_name(
        self, name: str, owner_id: str | None = None
    ) -> KnowledgeBase | None:
        statement = select(KnowledgeBase).where(KnowledgeBase.name == name)
        if owner_id is not None:
            statement = statement.where(KnowledgeBase.owner_id == owner_id)
        return self.db.scalar(statement)

    def list_all(self, owner_id: str | None = None) -> list[KnowledgeBase]:
        statement = select(KnowledgeBase)
        if owner_id is not None:
            statement = statement.where(KnowledgeBase.owner_id == owner_id)
        statement = statement.order_by(
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

    def update(
        self,
        knowledge_base: KnowledgeBase,
        *,
        name: str | None = None,
        description: str | None = None,
        update_name: bool = False,
        update_description: bool = False,
        web_access_policy: KnowledgeBaseWebPolicy | str | None = None,
        update_web_access_policy: bool = False,
    ) -> KnowledgeBase:
        if update_name:
            knowledge_base.name = str(name)
        if update_description:
            knowledge_base.description = description
        if update_web_access_policy:
            knowledge_base.web_access_policy = (
                web_access_policy.value
                if isinstance(web_access_policy, KnowledgeBaseWebPolicy)
                else str(web_access_policy)
            )
        self.db.flush()
        self.db.refresh(knowledge_base)
        return knowledge_base

    def clear_building_if_matches(
        self,
        knowledge_base_id: str,
        expected_collection_name: str,
    ) -> bool:
        statement = (
            update(KnowledgeBase)
            .where(
                KnowledgeBase.id == str(knowledge_base_id),
                KnowledgeBase.building_collection_name
                == expected_collection_name,
            )
            .values(
                building_collection_name=None,
                building_embedding_config_hash=None,
                rebuild_status="IDLE",
                rebuild_run_id=None,
                building_started_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        result = self.db.execute(statement)
        return result.rowcount == 1

    def clear_cleanup_if_matches(
        self,
        knowledge_base_id: str,
        expected_collection_name: str,
    ) -> bool:
        statement = (
            update(KnowledgeBase)
            .where(
                KnowledgeBase.id == str(knowledge_base_id),
                KnowledgeBase.cleanup_collection_name
                == expected_collection_name,
            )
            .values(cleanup_collection_name=None)
            .execution_options(synchronize_session=False)
        )
        result = self.db.execute(statement)
        return result.rowcount == 1

    def clear_previous_if_matches(
        self,
        knowledge_base_id: str,
        expected_collection_name: str,
    ) -> bool:
        statement = (
            update(KnowledgeBase)
            .where(
                KnowledgeBase.id == str(knowledge_base_id),
                KnowledgeBase.previous_collection_name
                == expected_collection_name,
            )
            .values(
                previous_collection_name=None,
                previous_embedding_config_hash=None,
            )
            .execution_options(synchronize_session=False)
        )
        result = self.db.execute(statement)
        return result.rowcount == 1

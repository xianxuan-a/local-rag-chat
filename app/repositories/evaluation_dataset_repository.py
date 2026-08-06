"""Persistence helpers for reusable, owner-scoped evaluation datasets."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EvaluationDataset


class EvaluationDatasetRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, dataset_id: str) -> EvaluationDataset | None:
        return self.db.get(EvaluationDataset, str(dataset_id))

    def get_by_owner_name(
        self, owner_id: str, name: str
    ) -> EvaluationDataset | None:
        return self.db.scalar(
            select(EvaluationDataset).where(
                EvaluationDataset.owner_id == str(owner_id),
                EvaluationDataset.name == name,
            )
        )

    def add(self, dataset: EvaluationDataset) -> EvaluationDataset:
        self.db.add(dataset)
        self.db.flush()
        self.db.refresh(dataset)
        return dataset

    def list_for_user(
        self,
        user_id: str,
        *,
        is_admin: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[EvaluationDataset], int]:
        filters = (
            ()
            if is_admin
            else (EvaluationDataset.owner_id == str(user_id),)
        )
        total = int(
            self.db.scalar(
                select(func.count(EvaluationDataset.id)).where(*filters)
            )
            or 0
        )
        items = list(
            self.db.scalars(
                select(EvaluationDataset)
                .where(*filters)
                .order_by(
                    EvaluationDataset.created_at.desc(),
                    EvaluationDataset.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            ).all()
        )
        return items, total

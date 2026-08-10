"""Transactional administrator operations for users and their audit trail."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ResourceNotFoundException,
    ValidationException,
)
from app.core.security import normalize_identity
from app.models import User, UserAdminAuditEvent, UserRole
from app.schemas.user_admin import AdminUserUpdate


class UserAdminService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_users(
        self,
        *,
        query: str | None,
        role: UserRole | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        statement = select(User)
        count_statement = select(func.count()).select_from(User)
        filters = []
        if query:
            normalized = normalize_identity(query)
            if normalized:
                pattern = f"%{normalized}%"
                filters.append(
                    or_(
                        User.username_normalized.like(pattern),
                        User.email_normalized.like(pattern),
                    )
                )
        if role is not None:
            filters.append(User.role == role.value)
        if is_active is not None:
            filters.append(User.is_active == is_active)
        if filters:
            statement = statement.where(*filters)
            count_statement = count_statement.where(*filters)
        items = list(
            self.db.scalars(
                statement.order_by(User.created_at.desc(), User.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = int(self.db.scalar(count_statement) or 0)
        return items, total

    def update_user(
        self,
        *,
        actor: User,
        target_user_id: str,
        payload: AdminUserUpdate,
        request_id: str,
    ) -> User:
        if payload.role is None and payload.is_active is None:
            raise ValidationException(
                "role 和 is_active 至少提供一项", status_code=422
            )
        target = self.db.get(User, target_user_id)
        if target is None:
            raise ResourceNotFoundException("用户不存在")
        desired_role = payload.role.value if payload.role is not None else target.role
        desired_active = (
            payload.is_active if payload.is_active is not None else target.is_active
        )
        removes_actor_access = actor.id == target.id and (
            desired_role != UserRole.ADMIN.value or not desired_active
        )
        if removes_actor_access:
            raise ConflictException("管理员不能降级或停用自己的账户")
        before = {"role": target.role, "is_active": target.is_active}
        after = {"role": desired_role, "is_active": desired_active}
        if before == after:
            return target

        if (
            target.role == UserRole.ADMIN.value
            and target.is_active
            and (desired_role != UserRole.ADMIN.value or not desired_active)
        ):
            other_admins = self.db.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.id != target.id,
                    User.role == UserRole.ADMIN.value,
                    User.is_active.is_(True),
                )
            )
            if not other_admins:
                raise ConflictException("不能移除最后一个有效管理员")

        target.role = desired_role
        target.is_active = desired_active
        self.db.add(
            UserAdminAuditEvent(
                actor_user_id=actor.id,
                target_user_id=target.id,
                action="USER_UPDATED",
                before_state=before,
                after_state=after,
                reason=payload.reason,
                request_id=str(UUID(request_id)),
            )
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if "last_active_admin" in str(exc.orig):
                raise ConflictException("不能移除最后一个有效管理员") from exc
            raise
        self.db.refresh(target)
        return target

    def list_audit_events(
        self,
        *,
        target_user_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[UserAdminAuditEvent], int]:
        statement = select(UserAdminAuditEvent)
        count_statement = select(func.count()).select_from(UserAdminAuditEvent)
        if target_user_id is not None:
            statement = statement.where(
                UserAdminAuditEvent.target_user_id == target_user_id
            )
            count_statement = count_statement.where(
                UserAdminAuditEvent.target_user_id == target_user_id
            )
        items = list(
            self.db.scalars(
                statement.order_by(
                    UserAdminAuditEvent.created_at.desc(),
                    UserAdminAuditEvent.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        )
        total = int(self.db.scalar(count_statement) or 0)
        return items, total

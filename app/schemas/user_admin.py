"""Administrator-facing user management schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import UserRole
from app.schemas.auth import UserResponse


class AdminUserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AdminUserPage(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class UserAdminAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID
    target_user_id: UUID
    action: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    reason: str | None
    request_id: UUID
    created_at: datetime


class UserAdminAuditEventPage(BaseModel):
    items: list[UserAdminAuditEventResponse]
    total: int
    limit: int
    offset: int

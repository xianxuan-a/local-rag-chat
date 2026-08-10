"""Administrator-only user management and audit endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import AdminUser
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.models import UserRole
from app.schemas.auth import UserResponse
from app.schemas.user_admin import (
    AdminUserPage,
    AdminUserUpdate,
    UserAdminAuditEventPage,
    UserAdminAuditEventResponse,
)
from app.services.runtime_coordinator import RuntimeCoordinator, get_runtime_coordinator
from app.services.user_admin_service import UserAdminService


router = APIRouter(prefix="/users", tags=["users"])
DatabaseSession = Annotated[Session, Depends(get_db)]
RagRuntime = Annotated[RuntimeCoordinator, Depends(get_runtime_coordinator)]


@router.get("", response_model=ApiResponse[AdminUserPage])
def list_users(
    db: DatabaseSession,
    _: AdminUser,
    query: Annotated[str | None, Query(max_length=320)] = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = UserAdminService(db).list_users(
        query=query,
        role=role,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return success_response(
        AdminUserPage(
            items=[UserResponse.model_validate(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/audit-events",
    response_model=ApiResponse[UserAdminAuditEventPage],
)
def list_user_audit_events(
    db: DatabaseSession,
    _: AdminUser,
    target_user_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = UserAdminService(db).list_audit_events(
        target_user_id=(str(target_user_id) if target_user_id else None),
        limit=limit,
        offset=offset,
    )
    return success_response(
        UserAdminAuditEventPage(
            items=[
                UserAdminAuditEventResponse.model_validate(item)
                for item in items
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
    )


@router.patch("/{user_id}", response_model=ApiResponse[UserResponse])
def update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    request: Request,
    db: DatabaseSession,
    runtime: RagRuntime,
    admin: AdminUser,
):
    with runtime.business_write("update_user"):
        user = UserAdminService(db).update_user(
            actor=admin,
            target_user_id=str(user_id),
            payload=payload,
            request_id=request.state.request_id,
        )
    return success_response(UserResponse.model_validate(user))

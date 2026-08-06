"""Authentication and explicit bootstrap routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser
from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationException
from app.core.response import ApiResponse, success_response
from app.core.security import secrets_equal
from app.database.sqlite import get_db
from app.schemas.auth import (
    BootstrapAdminRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService
from app.services.runtime_coordinator import RuntimeCoordinator, get_runtime_coordinator


router = APIRouter(prefix="/auth", tags=["auth"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[RuntimeCoordinator, Depends(get_runtime_coordinator)]


@router.post(
    "/register",
    response_model=ApiResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
):
    if not settings.ALLOW_REGISTRATION:
        raise ValidationException("当前部署未开放用户注册", status_code=403)
    with runtime.business_write("register"):
        user = AuthService(db, settings).register(payload)
    return success_response(
        UserResponse.model_validate(user), status_code=status.HTTP_201_CREATED
    )


@router.post("/login", response_model=ApiResponse[TokenResponse])
def login(payload: LoginRequest, db: DatabaseSession, settings: AppSettings):
    user, token, jti = AuthService(db, settings).login(payload)
    return success_response(
        TokenResponse(
            access_token=token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            jti=jti,
            user=UserResponse.model_validate(user),
        )
    )


@router.post("/bootstrap", response_model=ApiResponse[UserResponse])
def bootstrap_admin(
    payload: BootstrapAdminRequest,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    bootstrap_secret: Annotated[str, Header(alias="X-Bootstrap-Secret")],
):
    if not secrets_equal(
        bootstrap_secret, settings.BOOTSTRAP_SECRET.get_secret_value()
    ):
        raise ValidationException("bootstrap Secret 无效", status_code=403)
    with runtime.business_write("bootstrap_admin"):
        user = AuthService(db, settings).bootstrap_admin(payload)
    return success_response(UserResponse.model_validate(user))


@router.get("/me", response_model=ApiResponse[UserResponse])
def me(user: CurrentUser):
    return success_response(UserResponse.model_validate(user))

"""Authentication dependencies that re-read role and active state per request."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationException
from app.core.security import decode_access_token
from app.database.sqlite import get_db
from app.models import User, UserRole
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


bearer = HTTPBearer(auto_error=False)
LOCAL_SINGLE_USER_ID = "00000000-0000-0000-0000-000000000001"


def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer)
    ],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    if not settings.AUTH_REQUIRED:
        user = db.get(User, LOCAL_SINGLE_USER_ID)
        if user is None:
            raise RuntimeError("本地单用户记录不存在，请先升级数据库")
        request.state.user_id = user.id
        return user

    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise ValidationException("需要 Bearer 访问令牌", status_code=401)
    payload = decode_access_token(credentials.credentials, settings)
    user = db.get(User, str(payload["sub"]))
    if user is None or not user.is_active:
        raise ValidationException("用户不存在或已禁用", status_code=401)
    request.state.user_id = user.id
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != UserRole.ADMIN.value:
        raise ValidationException("需要管理员权限", status_code=403)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]


def get_business_write_permit(
    runtime: Annotated[RuntimeCoordinator, Depends(get_runtime_coordinator)],
) -> Generator[None, None, None]:
    with runtime.business_write("http_business_write"):
        yield


BusinessWritePermit = Annotated[
    None, Depends(get_business_write_permit, scope="request")
]

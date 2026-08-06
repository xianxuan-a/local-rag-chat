"""User registration, bootstrap, and login."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictException, ValidationException
from app.core.security import (
    create_access_token,
    hash_password,
    normalize_identity,
    verify_password,
)
from app.models import User, UserRole
from app.schemas.auth import BootstrapAdminRequest, LoginRequest, RegisterRequest


BOOTSTRAP_USER_ID = "00000000-0000-0000-0000-000000000001"


class AuthService:
    def __init__(
        self, db: Session, settings: Settings | None = None
    ) -> None:
        self.db = db
        self.settings = settings

    def register(self, payload: RegisterRequest) -> User:
        username_normalized = normalize_identity(payload.username)
        email_normalized = (
            normalize_identity(payload.email) if payload.email else None
        )
        if not username_normalized:
            raise ValidationException("用户名规范化后不能为空")
        self._validate_normalized_lengths(
            username_normalized, email_normalized
        )
        user = User(
            username=payload.username.strip(),
            username_normalized=username_normalized,
            email=payload.email.strip() if payload.email else None,
            email_normalized=email_normalized,
            password_hash=hash_password(payload.password),
            role=UserRole.USER.value,
            is_active=True,
            must_change_password=False,
        )
        self.db.add(user)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictException("用户名或邮箱已存在") from exc
        self.db.refresh(user)
        return user

    def bootstrap_admin(self, payload: BootstrapAdminRequest) -> User:
        user = self.db.get(User, BOOTSTRAP_USER_ID)
        if user is None:
            raise ConflictException("bootstrap 用户记录不存在，请先执行迁移")
        if user.is_active or user.password_hash != "!":
            raise ConflictException("bootstrap admin 已初始化，拒绝重复执行")
        user.username = payload.username.strip()
        user.username_normalized = normalize_identity(payload.username)
        user.email = payload.email.strip() if payload.email else None
        user.email_normalized = (
            normalize_identity(payload.email) if payload.email else None
        )
        self._validate_normalized_lengths(
            user.username_normalized, user.email_normalized
        )
        user.password_hash = hash_password(payload.password)
        user.role = UserRole.ADMIN.value
        user.is_active = True
        user.must_change_password = False
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictException("bootstrap 用户名或邮箱与现有用户冲突") from exc
        self.db.refresh(user)
        return user

    def login(self, payload: LoginRequest) -> tuple[User, str, str]:
        if self.settings is None:
            raise RuntimeError("登录服务缺少应用 Settings")
        normalized = normalize_identity(payload.identity)
        user = self.db.scalar(
            select(User).where(
                or_(
                    User.username_normalized == normalized,
                    User.email_normalized == normalized,
                )
            )
        )
        if (
            user is None
            or not user.is_active
            or not verify_password(payload.password, user.password_hash)
        ):
            raise ValidationException(
                "用户名/邮箱或密码错误", status_code=401
            )
        token, jti = create_access_token(user.id, self.settings)
        return user, token, jti

    @staticmethod
    def _validate_normalized_lengths(
        username: str, email: str | None
    ) -> None:
        if not username or len(username) > 200:
            raise ValidationException("用户名规范化后长度无效")
        if email is not None and len(email) > 640:
            raise ValidationException("邮箱规范化后长度无效")

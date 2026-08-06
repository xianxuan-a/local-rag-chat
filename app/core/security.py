"""Identity normalization, bcrypt boundaries, and JWT primitives."""

from __future__ import annotations

import secrets
import unicodedata
from datetime import timedelta
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import Settings
from app.core.exceptions import ConfigurationException, ValidationException
from app.models import utc_now


def normalize_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


def validate_password_bytes(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) < 12:
        raise ValidationException("密码必须至少包含 12 个 UTF-8 字节")
    if len(encoded) > 72:
        raise ValidationException("密码不能超过 bcrypt 的 72 个 UTF-8 字节限制")
    return encoded


def hash_password(password: str) -> str:
    return bcrypt.hashpw(validate_password_bytes(password), bcrypt.gensalt()).decode(
        "ascii"
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        encoded = validate_password_bytes(password)
        return bcrypt.checkpw(encoded, password_hash.encode("ascii"))
    except (ValueError, TypeError, ValidationException):
        return False


def create_access_token(user_id: str, settings: Settings) -> tuple[str, str]:
    secret = settings.JWT_SECRET.get_secret_value()
    if not secret:
        raise ConfigurationException(
            "JWT_SECRET 未配置；请显式运行 scripts/init_secrets.py"
        )
    now = utc_now()
    jti = str(uuid4())
    token = jwt.encode(
        {
            "sub": str(user_id),
            "jti": jti,
            "iat": now,
            "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        },
        secret,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, jti


def decode_access_token(token: str, settings: Settings) -> dict[str, object]:
    secret = settings.JWT_SECRET.get_secret_value()
    if not secret:
        raise ConfigurationException("JWT_SECRET 未配置")
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "jti", "iat", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise ValidationException("访问令牌无效或已过期", status_code=401) from exc
    return payload


def secrets_equal(provided: str, expected: str) -> bool:
    return bool(expected) and secrets.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    )

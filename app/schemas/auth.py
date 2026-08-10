"""Authentication request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    password: str

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


class LoginRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=320)
    password: str

    @field_validator("identity", mode="before")
    @classmethod
    def normalize_identity_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class BootstrapAdminRequest(RegisterRequest):
    pass


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str | None
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    jti: str
    user: UserResponse

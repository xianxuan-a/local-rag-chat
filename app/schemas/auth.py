"""Authentication request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    password: str

    @field_validator("email")
    @classmethod
    def empty_email_to_none(cls, value: str | None) -> str | None:
        return value or None


class LoginRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=320)
    password: str


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

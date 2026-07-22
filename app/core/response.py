"""Shared API response envelope and JSON response helpers."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from starlette.responses import JSONResponse


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Uniform response envelope for successful and failed API calls."""

    code: int
    message: str
    data: T | None = None


def success_response(
    data: Any = None,
    message: str = "success",
    status_code: int = 200,
) -> JSONResponse:
    """Build a successful JSON response while preserving the HTTP status."""

    payload = ApiResponse[Any](code=0, message=message, data=data)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload, exclude_none=False),
    )


def error_response(
    code: int,
    message: str,
    status_code: int,
    data: Any = None,
) -> JSONResponse:
    """Build a failed JSON response using the same public envelope."""

    payload = ApiResponse[Any](code=code, message=message, data=data)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload, exclude_none=False),
    )

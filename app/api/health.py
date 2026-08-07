"""Cheap liveness and dependency-aware readiness endpoints."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.response import error_response, success_response
from app.database.migrations import verify_database_at_head
from app.database.sqlite import get_db
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(tags=["health"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[
    RuntimeCoordinator, Depends(get_runtime_coordinator)
]


@router.get("/health/live")
def live():
    return success_response({"status": "live"})


@router.get("/health/ready")
def ready(
    request: Request,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
):
    checks: dict[str, str] = {}
    failures: list[str] = []
    try:
        db.execute(text("SELECT 1"))
        checks["sqlite"] = "ok"
    except Exception:
        checks["sqlite"] = "failed"
        failures.append("sqlite")
    try:
        engine = getattr(request.app.state, "engine", None)
        if engine is None:
            raise RuntimeError("database engine is not initialized")
        verify_database_at_head(engine)
        checks["migration"] = "ok"
    except Exception:
        checks["migration"] = "failed"
        failures.append("migration")
    for label, path in (
        ("log_dir", settings.LOG_DIR),
        ("data_dir", settings.DATA_DIR),
        ("upload_dir", settings.UPLOAD_DIR),
        ("chroma_dir", settings.CHROMA_DIR),
        ("metadata_dir", settings.METADATA_DIR),
        ("chat_history_dir", settings.CHAT_HISTORY_DIR),
        ("backup_dir", settings.BACKUP_DIR),
        ("evaluation_dir", settings.EVALUATION_DIR),
    ):
        if path.is_dir() and os.access(path, os.R_OK | os.W_OK):
            checks[label] = "ok"
        else:
            checks[label] = "failed"
            failures.append(label)
    try:
        runtime.vector_store.client.heartbeat()
        checks["chroma"] = "ok"
    except Exception:
        checks["chroma"] = "failed"
        failures.append("chroma")
    worker = getattr(request.app.state, "job_worker", None)
    if worker is not None and worker.is_alive:
        checks["job_worker"] = "ok"
    else:
        checks["job_worker"] = "failed"
        failures.append("job_worker")
    payload = {
        "status": "ready" if not failures else "not_ready",
        "checks": checks,
    }
    if failures:
        return error_response(
            code=503,
            message="service is not ready",
            status_code=503,
            data=payload,
        )
    return success_response(payload)


@router.get("/health")
def compatibility_health():
    """Backward-compatible cheap liveness alias."""

    return success_response({"status": "ok"})

"""Prometheus scrape endpoint protected by a dedicated long-lived token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationException
from app.core.security import secrets_equal
from app.database.sqlite import get_db
from app.models import Job, JobStatus


router = APIRouter(tags=["metrics"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
NONTERMINAL_JOBS = Gauge(
    "local_rag_nonterminal_jobs",
    "Number of queued, running, or cancel-requested jobs",
)


@router.get("/metrics", include_in_schema=False)
def metrics(
    db: DatabaseSession,
    settings: AppSettings,
    scrape_token: Annotated[str, Header(alias="X-Metrics-Scrape-Token")],
) -> Response:
    if not secrets_equal(
        scrape_token, settings.METRICS_SCRAPE_TOKEN.get_secret_value()
    ):
        raise ValidationException("metrics scrape token 无效", status_code=401)
    count = db.scalar(
        select(func.count(Job.id)).where(
            Job.status.in_(
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.CANCEL_REQUESTED.value,
                )
            )
        )
    )
    NONTERMINAL_JOBS.set(int(count or 0))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

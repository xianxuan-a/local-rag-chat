"""Reusable evaluation datasets, durable runs, reports, and case history."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import BusinessWritePermit, CurrentUser
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ConflictException,
    ResourceNotFoundException,
)
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.models import (
    EvaluationDataset,
    Job,
    JobStatus,
    JobType,
    UserRole,
)
from app.repositories.evaluation_dataset_repository import (
    EvaluationDatasetRepository,
)
from app.schemas.evaluation import (
    EvaluationCasePage,
    EvaluationDatasetPage,
    EvaluationDatasetResponse,
    EvaluationRunCreate,
    EvaluationRunPage,
    EvaluationRunResponse,
    EvaluationSummaryResponse,
)
from app.schemas.job import JobResponse
from app.services.evaluation_catalog_service import (
    EvaluationCatalogService,
    evaluation_counts,
)
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(prefix="/evaluations", tags=["evaluations"])
datasets_router = APIRouter(
    prefix="/evaluation-datasets", tags=["evaluation-datasets"]
)
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[
    RuntimeCoordinator, Depends(get_runtime_coordinator)
]
MAX_REPORT_BYTES = 20 * 1024 * 1024


@datasets_router.post(
    "",
    response_model=ApiResponse[EvaluationDatasetResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_evaluation_dataset(
    name: Annotated[str, Form(min_length=1, max_length=100)],
    dataset_file: Annotated[UploadFile, File()],
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
    _write_permit: BusinessWritePermit,
    description: Annotated[str | None, Form(max_length=1000)] = None,
):
    raw = dataset_file.file.read(5 * 1024 * 1024 + 1)
    dataset = EvaluationCatalogService(
        db, settings, runtime
    ).register_dataset(
        owner=user,
        name=name,
        description=description,
        original_filename=dataset_file.filename or "dataset.jsonl",
        raw=raw,
    )
    return success_response(
        EvaluationDatasetResponse.model_validate(dataset),
        status_code=status.HTTP_201_CREATED,
    )


@datasets_router.get(
    "",
    response_model=ApiResponse[EvaluationDatasetPage],
)
def list_evaluation_datasets(
    db: DatabaseSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = EvaluationDatasetRepository(db).list_for_user(
        user.id,
        is_admin=user.role == UserRole.ADMIN.value,
        limit=limit,
        offset=offset,
    )
    return success_response(
        EvaluationDatasetPage(
            items=[
                EvaluationDatasetResponse.model_validate(item)
                for item in items
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
    )


@datasets_router.get(
    "/{dataset_id}",
    response_model=ApiResponse[EvaluationDatasetResponse],
)
def get_evaluation_dataset(
    dataset_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    dataset = EvaluationCatalogService(
        db, settings, runtime
    ).get_owned_dataset(str(dataset_id), user)
    return success_response(
        EvaluationDatasetResponse.model_validate(dataset)
    )


@router.post(
    "/runs",
    response_model=ApiResponse[EvaluationRunResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
def create_evaluation_run(
    payload: EvaluationRunCreate,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
    _write_permit: BusinessWritePermit,
):
    service = EvaluationCatalogService(db, settings, runtime)
    job = service.submit_run(payload, user)
    dataset = service.get_owned_dataset(str(payload.dataset_id), user)
    return success_response(
        _run_response(job, dataset),
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.post(
    "",
    response_model=ApiResponse[JobResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_legacy_evaluation(
    knowledge_base_id: Annotated[UUID, Form()],
    dataset_file: Annotated[UploadFile, File()],
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
    _write_permit: BusinessWritePermit,
    top_k: Annotated[int, Form(ge=1, le=100)] = 4,
    score_threshold: Annotated[
        float | None, Form(ge=-1.0, le=1.0)
    ] = None,
    max_calls: Annotated[int, Form(ge=2, le=1000)] = 200,
    max_generation_tokens: Annotated[
        int, Form(ge=1, le=2_000_000)
    ] = 100000,
    max_runtime_seconds: Annotated[
        int, Form(ge=1, le=21600)
    ] = 1800,
):
    raw = dataset_file.file.read(5 * 1024 * 1024 + 1)
    original_name = Path(
        dataset_file.filename or "dataset.jsonl"
    ).stem[:80]
    service = EvaluationCatalogService(db, settings, runtime)
    candidate_name = original_name or "历史评测数据集"
    existing = EvaluationDatasetRepository(db).get_by_owner_name(
        user.id, candidate_name
    )
    if existing is not None and existing.sha256 != hashlib.sha256(raw).hexdigest():
        candidate_name = (
            f"{candidate_name[:67]}-{hashlib.sha256(raw).hexdigest()[:12]}"
        )
    dataset = service.register_dataset(
        owner=user,
        name=candidate_name,
        description="由兼容评测接口注册",
        original_filename=dataset_file.filename or "dataset.jsonl",
        raw=raw,
    )
    job = service.submit_run(
        EvaluationRunCreate(
            dataset_id=UUID(dataset.id),
            knowledge_base_id=knowledge_base_id,
            run_name="历史评测",
            mode="rag",
            top_k=top_k,
            score_threshold=score_threshold,
            max_calls=max_calls,
            max_generation_tokens=max_generation_tokens,
            max_runtime_seconds=max_runtime_seconds,
        ),
        user,
    )
    return success_response(
        JobResponse.model_validate(job),
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.get(
    "",
    response_model=ApiResponse[EvaluationRunPage],
)
def list_evaluations(
    db: DatabaseSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    knowledge_base_id: UUID | None = None,
    dataset_id: UUID | None = None,
):
    filters = [Job.job_type == JobType.RAG_EVALUATION.value]
    if user.role != UserRole.ADMIN.value:
        filters.append(Job.created_by_id == user.id)
    if knowledge_base_id is not None:
        filters.append(Job.resource_id == str(knowledge_base_id))
    if dataset_id is not None:
        filters.append(Job.evaluation_dataset_id == str(dataset_id))
    total = int(
        db.scalar(select(func.count(Job.id)).where(*filters)) or 0
    )
    jobs = list(
        db.scalars(
            select(Job)
            .where(*filters)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    dataset_ids = {
        item.evaluation_dataset_id
        for item in jobs
        if item.evaluation_dataset_id
    }
    datasets = {
        item.id: item
        for item in db.scalars(
            select(EvaluationDataset).where(
                EvaluationDataset.id.in_(dataset_ids)
            )
        ).all()
    } if dataset_ids else {}
    return success_response(
        EvaluationRunPage(
            items=[
                _run_response(job, datasets.get(job.evaluation_dataset_id))
                for job in jobs
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/summary",
    response_model=ApiResponse[EvaluationSummaryResponse],
)
def get_evaluation_summary(db: DatabaseSession, user: CurrentUser):
    run_count, dataset_count, status_counts = evaluation_counts(db, user)
    return success_response(
        EvaluationSummaryResponse(
            run_count=run_count,
            dataset_count=dataset_count,
            status_counts=status_counts,
        )
    )


@router.get(
    "/{job_id}",
    response_model=ApiResponse[EvaluationRunResponse],
)
def get_evaluation(
    job_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    user: CurrentUser,
):
    job = _owned_evaluation(db, str(job_id), user)
    dataset = (
        db.get(EvaluationDataset, job.evaluation_dataset_id)
        if job.evaluation_dataset_id
        else None
    )
    report = (
        _read_report(job, settings)
        if job.status == JobStatus.SUCCEEDED.value
        else None
    )
    return success_response(_run_response(job, dataset, report))


@router.get(
    "/{job_id}/report",
    response_model=ApiResponse[dict[str, Any]],
)
def get_evaluation_report(
    job_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    user: CurrentUser,
):
    return success_response(
        _read_report(_owned_evaluation(db, str(job_id), user), settings)
    )


@router.get(
    "/{job_id}/cases",
    response_model=ApiResponse[EvaluationCasePage],
)
def get_evaluation_cases(
    job_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    failed_only: bool = False,
):
    report = _read_report(
        _owned_evaluation(db, str(job_id), user), settings
    )
    raw_cases = report.get("cases")
    if not isinstance(raw_cases, list):
        raise ConflictException("评测报告缺少案例列表")
    cases = [
        item
        for item in raw_cases
        if isinstance(item, dict)
        and (not failed_only or item.get("error") is not None)
    ]
    return success_response(
        EvaluationCasePage(
            items=cases[offset : offset + limit],
            total=len(cases),
            limit=limit,
            offset=offset,
            failed_only=failed_only,
        )
    )


def _owned_evaluation(db: Session, job_id: str, user: object) -> Job:
    job = db.get(Job, job_id)
    if (
        job is None
        or job.job_type != JobType.RAG_EVALUATION.value
        or (
            user.role != UserRole.ADMIN.value
            and job.created_by_id != user.id
        )
    ):
        raise ResourceNotFoundException("评测运行不存在")
    return job


def _run_response(
    job: Job,
    dataset: EvaluationDataset | None,
    report: dict[str, Any] | None = None,
) -> EvaluationRunResponse:
    mode = job.evaluation_mode or "rag"
    return EvaluationRunResponse(
        job=JobResponse.model_validate(job),
        dataset=(
            EvaluationDatasetResponse.model_validate(dataset)
            if dataset is not None
            else None
        ),
        mode=mode,
        run_name=job.evaluation_run_name or "历史评测",
        outcome=(
            report.get("outcome")
            if isinstance(report, dict)
            and report.get("outcome")
            in {"SUCCESS", "PARTIAL_SUCCESS"}
            else (
                job.result.get("outcome")
                if isinstance(job.result, dict)
                and job.result.get("outcome")
                in {"SUCCESS", "PARTIAL_SUCCESS"}
                else None
            )
        ),
        metrics=(
            report.get("metrics")
            if isinstance(report, dict)
            and isinstance(report.get("metrics"), dict)
            else None
        ),
    )


def _read_report(job: Job, settings: Settings) -> dict[str, Any]:
    if job.status != JobStatus.SUCCEEDED.value:
        raise ConflictException("评测报告尚未成功生成")
    if not job.report_path or not job.report_sha256:
        raise ConflictException("评测运行缺少报告完整性信息")
    report_root = (settings.EVALUATION_DIR / "reports").resolve()
    configured_path = Path(job.report_path)
    if configured_path.is_symlink():
        raise ConflictException("评测报告不能是符号链接")
    try:
        report_path = configured_path.resolve(strict=True)
        report_path.relative_to(report_root)
    except (OSError, ValueError) as exc:
        raise ConflictException("评测报告路径无效") from exc
    if not report_path.is_file() or report_path.is_symlink():
        raise ConflictException("评测报告不是普通文件")
    if report_path.stat().st_size > MAX_REPORT_BYTES:
        raise ConflictException("评测报告超过读取上限")
    raw = report_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != job.report_sha256:
        raise ConflictException("评测报告完整性校验失败")
    try:
        report = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConflictException("评测报告格式无效") from exc
    if not isinstance(report, dict):
        raise ConflictException("评测报告必须是 JSON 对象")
    return report

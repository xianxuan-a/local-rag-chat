"""Stable bounded pagination and query-count regression contracts."""

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.models import FileRecord, FileStatus, Job, JobStatus, JobType
from app.repositories.file_repository import FileRepository
from app.repositories.job_repository import JobRepository


def _create_knowledge_base(client: TestClient) -> str:
    response = client.post(
        "/api/knowledge-bases",
        json={"name": "pagination-performance"},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def test_file_and_job_pages_are_stable_bounded_and_constant_query(
    client: TestClient,
    app: FastAPI,
) -> None:
    knowledge_base_id = _create_knowledge_base(client)
    current_user = client.get("/api/auth/me").json()["data"]
    now = datetime.now(UTC)

    with app.state.session_factory() as db:
        db.add_all(
            [
                FileRecord(
                    knowledge_base_id=knowledge_base_id,
                    original_name=f"document-{index:04d}.txt",
                    stored_name=f"pagination-{index:04d}.txt",
                    file_path=f"uploads/pagination-{index:04d}.txt",
                    file_type="TXT",
                    file_size=1,
                    md5=f"{index:032x}",
                    status=FileStatus.PENDING,
                )
                for index in range(1_000)
            ]
        )
        db.add_all(
            [
                Job(
                    job_type=JobType.FILE_PROCESS.value,
                    status=JobStatus.SUCCEEDED.value,
                    created_by_id=current_user["id"],
                    resource_type="FILE",
                    progress=100,
                    run_after=now,
                )
                for _ in range(1_000)
            ]
        )
        db.commit()

    with app.state.session_factory() as db:
        query_count = 0

        def count_query(*_args, **_kwargs) -> None:
            nonlocal query_count
            query_count += 1

        event.listen(app.state.engine, "before_cursor_execute", count_query)
        try:
            first_page, total = FileRepository(db).list_page_with_processing_jobs(
                knowledge_base_id,
                limit=200,
                offset=0,
            )
        finally:
            event.remove(app.state.engine, "before_cursor_execute", count_query)

        assert total == 1_000
        assert len(first_page) == 200
        assert query_count == 2

        file_ids: list[str] = []
        job_ids: list[str] = []
        for offset in range(0, 1_000, 200):
            file_page, file_total = FileRepository(
                db
            ).list_page_with_processing_jobs(
                knowledge_base_id,
                limit=200,
                offset=offset,
            )
            job_page, job_total = JobRepository(db).list_page_for_user(
                current_user["id"],
                is_admin=False,
                limit=200,
                offset=offset,
            )
            assert file_total == 1_000
            assert job_total == 1_000
            file_ids.extend(record.id for record, _job in file_page)
            job_ids.extend(job.id for job in job_page)

        assert len(file_ids) == len(set(file_ids)) == 1_000
        assert len(job_ids) == len(set(job_ids)) == 1_000

    file_page_response = client.get(
        "/api/files/page",
        params={
            "knowledge_base_id": knowledge_base_id,
            "limit": 25,
            "offset": 25,
        },
    )
    assert file_page_response.status_code == 200
    assert file_page_response.json()["data"]["total"] == 1_000
    assert len(file_page_response.json()["data"]["items"]) == 25

    job_page_response = client.get(
        "/api/jobs/page", params={"limit": 25, "offset": 25}
    )
    assert job_page_response.status_code == 200
    assert job_page_response.json()["data"]["total"] == 1_000
    assert len(job_page_response.json()["data"]["items"]) == 25

    legacy_files = client.get(
        "/api/files",
        params={"knowledge_base_id": knowledge_base_id, "limit": 10},
    )
    assert legacy_files.headers["Deprecation"] == "true"
    assert legacy_files.headers["X-Total-Count"] == "1000"
    assert len(legacy_files.json()["data"]) == 10

    legacy_jobs = client.get("/api/jobs", params={"limit": 10})
    assert legacy_jobs.headers["Deprecation"] == "true"
    assert legacy_jobs.headers["X-Total-Count"] == "1000"
    assert len(legacy_jobs.json()["data"]) == 10

    assert client.get("/api/jobs/page", params={"limit": 201}).status_code == 422
    assert (
        client.get(
            "/api/files/page",
            params={"knowledge_base_id": knowledge_base_id, "limit": 201},
        ).status_code
        == 422
    )

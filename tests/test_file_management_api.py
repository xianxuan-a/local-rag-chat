"""File-management integration and transaction-compensation tests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import FileRecord, FileStatus
from app.repositories.file_repository import FileRepository
from app.services.file_service import FileService


def create_knowledge_base(client: TestClient, name: str) -> str:
    response = client.post("/api/knowledge-bases", json={"name": name})
    assert response.status_code == 201
    return response.json()["data"]["id"]


def upload_text(client: TestClient, knowledge_base_id: str, name: str) -> dict:
    response = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": (name, name.encode(), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()["data"]


def open_session(app: FastAPI) -> Session:
    return app.state.session_factory()


def test_list_detail_and_status_return_real_isolated_records(
    client: TestClient,
) -> None:
    first_kb = create_knowledge_base(client, "文件列表一")
    second_kb = create_knowledge_base(client, "文件列表二")
    first_file = upload_text(client, first_kb, "first.txt")
    upload_text(client, second_kb, "second.txt")

    listed = client.get("/api/files", params={"knowledge_base_id": first_kb})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [first_file["id"]]

    detail = client.get(f"/api/files/{first_file['id']}")
    assert detail.status_code == 200
    assert detail.json()["data"] == first_file

    assert detail.json()["data"]["status"] == "PENDING"


def test_empty_existing_knowledge_base_returns_empty_list(
    client: TestClient,
) -> None:
    knowledge_base_id = create_knowledge_base(client, "空知识库")

    response = client.get(
        "/api/files", params={"knowledge_base_id": knowledge_base_id}
    )

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_status_update_is_persisted_and_visible_through_api(
    client: TestClient,
    app: FastAPI,
    test_settings: Settings,
) -> None:
    knowledge_base_id = create_knowledge_base(client, "状态更新")
    uploaded = upload_text(client, knowledge_base_id, "status.txt")

    with open_session(app) as db:
        updated = FileService(db, test_settings).update_file_status(
            uploaded["id"],
            FileStatus.FAILED,
            chunk_count=3,
            error_message="解析失败",
        )
        assert updated.status is FileStatus.FAILED

    response = client.get(f"/api/files/{uploaded['id']}")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "FAILED"
    assert response.json()["data"]["chunk_count"] == 3
    assert response.json()["data"]["error_message"] == "解析失败"


def test_delete_removes_disk_record_and_unblocks_knowledge_base(
    client: TestClient,
    test_settings: Settings,
) -> None:
    knowledge_base_id = create_knowledge_base(client, "正常删除")
    uploaded = upload_text(client, knowledge_base_id, "delete.txt")
    stored_path = test_settings.DATA_DIR / uploaded["file_path"]
    assert stored_path.is_file()

    deleted = client.delete(f"/api/files/{uploaded['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["id"] == uploaded["id"]
    assert not stored_path.exists()
    assert client.get(f"/api/files/{uploaded['id']}").status_code == 404
    assert client.delete(f"/api/files/{uploaded['id']}").status_code == 404

    knowledge_base_delete = client.delete(
        f"/api/knowledge-bases/{knowledge_base_id}"
    )
    assert knowledge_base_delete.status_code == 200


def test_delete_cleans_stale_record_when_disk_file_is_missing(
    client: TestClient,
    test_settings: Settings,
) -> None:
    knowledge_base_id = create_knowledge_base(client, "缺失文件")
    uploaded = upload_text(client, knowledge_base_id, "missing.txt")
    stored_path = test_settings.DATA_DIR / uploaded["file_path"]
    stored_path.unlink()

    deleted = client.delete(f"/api/files/{uploaded['id']}")

    assert deleted.status_code == 200
    assert client.get(f"/api/files/{uploaded['id']}").status_code == 404


def test_delete_rejects_database_path_outside_upload_root(
    client: TestClient,
    app: FastAPI,
    test_settings: Settings,
) -> None:
    knowledge_base_id = create_knowledge_base(client, "越界路径")
    uploaded = upload_text(client, knowledge_base_id, "managed.txt")
    outside_path = test_settings.DATA_DIR.parent / uploaded["stored_name"]
    outside_path.write_bytes(b"must remain")

    with open_session(app) as db:
        record = db.get(FileRecord, uploaded["id"])
        assert record is not None
        record.file_path = f"../{uploaded['stored_name']}"
        db.commit()

    response = client.delete(f"/api/files/{uploaded['id']}")

    assert response.status_code == 400
    assert outside_path.read_bytes() == b"must remain"
    assert client.get(f"/api/files/{uploaded['id']}").status_code == 200
    outside_path.unlink()


def test_database_commit_failure_restores_quarantined_file(
    client: TestClient,
    app: FastAPI,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_base_id = create_knowledge_base(client, "提交失败")
    uploaded = upload_text(client, knowledge_base_id, "restore.txt")
    stored_path = test_settings.DATA_DIR / uploaded["file_path"]

    with open_session(app) as db:
        service = FileService(db, test_settings)

        def fail_commit() -> None:
            raise RuntimeError("forced commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="forced commit failure"):
            service.delete_file(uploaded["id"])

    assert stored_path.is_file()
    with open_session(app) as verification_db:
        assert verification_db.get(FileRecord, uploaded["id"]) is not None


def test_repository_md5_query_is_scoped_to_knowledge_base(
    client: TestClient,
    app: FastAPI,
) -> None:
    first_kb = create_knowledge_base(client, "MD5 一")
    second_kb = create_knowledge_base(client, "MD5 二")
    uploaded = upload_text(client, first_kb, "same.txt")

    with open_session(app) as db:
        repository = FileRepository(db)
        assert repository.get_by_md5(first_kb, uploaded["md5"]) is not None
        assert repository.get_by_md5(second_kb, uploaded["md5"]) is None
        assert list(db.scalars(select(FileRecord)).all())

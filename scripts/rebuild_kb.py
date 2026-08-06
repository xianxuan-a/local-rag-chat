"""HTTP-only client for asynchronous rebuild and Collection maintenance."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="通过 FastAPI 重建或维护知识库 Collection"
    )
    parser.add_argument("--knowledge-base-id", required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--rollback-to-previous", action="store_true")
    modes.add_argument("--abort-building", action="store_true")
    modes.add_argument("--cleanup-retired", action="store_true")
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("API_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument("--token", default=os.getenv("ACCESS_TOKEN"), required=False)
    parser.add_argument("--timeout-seconds", type=float, default=3600)
    parser.add_argument("--poll-interval-seconds", type=float, default=1)
    return parser


def _request_json(
    method: str,
    url: str,
    *,
    token: str,
    timeout: float,
) -> tuple[int, object]:
    response = requests.request(
        method,
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {
            "code": response.status_code,
            "message": "服务端返回非 JSON 响应",
        }


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.token:
        parser.error("--token 或 ACCESS_TOKEN 必须提供")
    if args.timeout_seconds <= 0 or args.poll_interval_seconds <= 0:
        parser.error("timeout 和 poll interval 必须大于 0")
    if args.rollback_to_previous:
        operation = "rollback"
    elif args.abort_building:
        operation = "abort-building"
    elif args.cleanup_retired:
        operation = "cleanup-retired"
    else:
        operation = "rebuild"

    base = args.api_base_url.rstrip("/")
    url = f"{base}/api/knowledge-bases/{args.knowledge_base_id}/{operation}"
    try:
        status_code, payload = _request_json(
            "POST", url, token=args.token, timeout=min(30, args.timeout_seconds)
        )
        if not 200 <= status_code < 300:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 2 if status_code in {400, 401, 403, 404, 409, 422} else 1
        if status_code != 202:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        data = payload.get("data") if isinstance(payload, dict) else None
        job_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(job_id, str):
            raise RuntimeError("202 响应缺少 Job ID")
        deadline = time.monotonic() + args.timeout_seconds
        while time.monotonic() < deadline:
            _, job_payload = _request_json(
                "GET",
                f"{base}/api/jobs/{job_id}",
                token=args.token,
                timeout=min(30, args.timeout_seconds),
            )
            job = (
                job_payload.get("data")
                if isinstance(job_payload, dict)
                else None
            )
            if isinstance(job, dict) and job.get("status") in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
            }:
                print(json.dumps(job_payload, ensure_ascii=False, indent=2))
                return 0 if job["status"] == "SUCCEEDED" else 1
            time.sleep(args.poll_interval_seconds)
        print(json.dumps({"message": "等待 Job 超时", "job_id": job_id}, ensure_ascii=False))
        return 1
    except requests.RequestException as exc:
        print(
            json.dumps(
                {"status": "ERROR", "message": f"无法连接服务：{type(exc).__name__}"},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())

"""HTTP-only client for knowledge-base Collection maintenance."""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests


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
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=os.getenv("REBUILD_HTTP_TIMEOUT_SECONDS", "3600"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds 必须大于 0")

    if args.rollback_to_previous:
        operation = "rollback"
    elif args.abort_building:
        operation = "abort-building"
    elif args.cleanup_retired:
        operation = "cleanup-retired"
    else:
        operation = "rebuild"

    base_url = args.api_base_url.rstrip("/")
    url = (
        f"{base_url}/api/knowledge-bases/"
        f"{args.knowledge_base_id}/{operation}"
    )
    try:
        response = requests.post(url, timeout=args.timeout_seconds)
    except requests.RequestException as exc:
        print(
            json.dumps(
                {"status": "ERROR", "message": f"无法连接服务：{type(exc).__name__}"},
                ensure_ascii=False,
            )
        )
        return 2

    try:
        payload = response.json()
    except ValueError:
        payload = {
            "status": "ERROR",
            "message": "服务端返回了非 JSON 响应",
            "http_status": response.status_code,
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if 200 <= response.status_code < 300:
        data = payload.get("data") if isinstance(payload, dict) else None
        if operation == "rebuild" and isinstance(data, dict):
            return 0 if data.get("status") == "SUCCESS" and data.get("switched") else 1
        return 0
    if response.status_code in {400, 401, 403, 404, 422}:
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())

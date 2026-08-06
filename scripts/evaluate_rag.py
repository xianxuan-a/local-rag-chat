"""HTTP-only bounded RAG evaluation submission client."""

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


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--token", default=os.getenv("ACCESS_TOKEN"))
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--score-threshold", type=float)
    parser.add_argument("--max-calls", type=int, default=200)
    parser.add_argument("--max-generation-tokens", type=int, default=100000)
    parser.add_argument("--max-runtime-seconds", type=int, default=1800)
    parser.add_argument("--poll-interval-seconds", type=float, default=1)
    parser.add_argument(
        "--report-output",
        type=Path,
        help="评估成功后将报告 JSON 保存到该本地路径",
    )
    args = parser.parse_args()
    if not args.token:
        parser.error("--token 或 ACCESS_TOKEN 必须提供")
    dataset = args.dataset.expanduser().resolve()
    if not dataset.is_file():
        parser.error("--dataset 文件不存在")

    headers = {"Authorization": f"Bearer {args.token}"}
    data = {
        "knowledge_base_id": args.knowledge_base_id,
        "top_k": args.top_k,
        "max_calls": args.max_calls,
        "max_generation_tokens": args.max_generation_tokens,
        "max_runtime_seconds": args.max_runtime_seconds,
    }
    if args.score_threshold is not None:
        data["score_threshold"] = args.score_threshold
    with dataset.open("rb") as source:
        response = requests.post(
            f"{args.api_base_url.rstrip('/')}/api/evaluations",
            headers=headers,
            data=data,
            files={"dataset_file": (dataset.name, source, "application/x-ndjson")},
            timeout=30,
        )
    payload = response.json()
    if response.status_code != 202:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    job_id = payload["data"]["id"]
    deadline = time.monotonic() + args.max_runtime_seconds + 60
    while time.monotonic() < deadline:
        job_response = requests.get(
            f"{args.api_base_url.rstrip('/')}/api/jobs/{job_id}",
            headers=headers,
            timeout=30,
        )
        job_payload = job_response.json()
        job = job_payload.get("data", {})
        if job.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            if job["status"] != "SUCCEEDED":
                print(json.dumps(job_payload, ensure_ascii=False, indent=2))
                return 1
            report_response = requests.get(
                (
                    f"{args.api_base_url.rstrip('/')}/api/evaluations/"
                    f"{job_id}/report"
                ),
                headers=headers,
                timeout=30,
            )
            report_payload = report_response.json()
            if report_response.status_code != 200:
                print(json.dumps(report_payload, ensure_ascii=False, indent=2))
                return 2
            report = report_payload.get("data", {})
            if args.report_output:
                output_path = args.report_output.expanduser().resolve()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            metrics = report.get("metrics", {})
            summary = {
                "job_id": job_id,
                "collection_name": report.get("collection_name"),
                "dataset_sha256": report.get("dataset_sha256"),
                "case_count": report.get("case_count"),
                "metrics": metrics,
                "report_output": (
                    str(args.report_output.expanduser().resolve())
                    if args.report_output
                    else None
                ),
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        time.sleep(args.poll_interval_seconds)
    print(json.dumps({"message": "等待评估 Job 超时", "job_id": job_id}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

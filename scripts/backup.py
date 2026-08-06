"""HTTP-only online logical backup submission and one-file retention tool."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio


def _submit(api_base_url: str, token: str) -> int:
    response = requests.post(
        f"{api_base_url.rstrip('/')}/api/backups",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0 if response.status_code == 202 else 1


def _expired_files(directory: Path, older_than_days: int) -> list[Path]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    result: list[Path] = []
    for path in sorted(directory.glob("*.zip"), key=lambda item: item.name):
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified < cutoff and path.is_file() and not path.is_symlink():
            result.append(path.resolve())
    return result


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    submit = subparsers.add_parser("submit")
    submit.add_argument("--api-base-url", default="http://localhost:8000")
    submit.add_argument("--token", required=True)
    retention = subparsers.add_parser("retention")
    retention.add_argument("--directory", type=Path, required=True)
    retention.add_argument("--older-than-days", type=int, required=True)
    retention.add_argument("--delete-one", type=Path)
    args = parser.parse_args()
    if args.command == "submit":
        return _submit(args.api_base_url, args.token)

    directory = args.directory.expanduser().resolve()
    expired = _expired_files(directory, args.older_than_days)
    if args.delete_one is None:
        for path in expired:
            print(path)
        return 0
    target = args.delete_one.expanduser().resolve()
    if target.parent != directory or target not in expired:
        raise SystemExit("--delete-one 必须是 dry-run 列出的一个明确过期文件")
    target.unlink()
    print(f"deleted: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

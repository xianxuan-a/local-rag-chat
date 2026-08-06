"""Offline-only restoration into a new target directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio
from app.core.config import get_settings
from app.services.backup_restore_service import BackupRestoreService


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="验证签名并将在线逻辑备份离线恢复到新目录"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    restored = BackupRestoreService(get_settings()).restore(
        args.archive, args.target
    )
    print(restored)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

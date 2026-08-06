"""Explicit offline bootstrap-admin initialization for a stopped instance."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio
from app.core.instance_lock import InstanceLock, instance_lock_path
from app.database.sqlite import init_database
from app.schemas.auth import BootstrapAdminRequest
from app.services.auth_service import AuthService


def bootstrap_admin(
    *,
    database: Path,
    data_dir: Path,
    username: str,
    email: str | None,
    password: str,
) -> str:
    database = database.expanduser().resolve()
    database_url = f"sqlite:///{database.as_posix()}"
    with InstanceLock(instance_lock_path(data_dir)):
        engine, session_factory = init_database(database_url)
        try:
            with session_factory() as db:
                user = AuthService(db).bootstrap_admin(
                    BootstrapAdminRequest(
                        username=username,
                        email=email,
                        password=password,
                    )
                )
                return user.id
        finally:
            engine.dispose()


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description=(
            "API 停止时将迁移创建的不可登录 bootstrap 记录"
            "显式初始化为可登录管理员"
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "metadata"
        / "local_rag_chat.db",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=PROJECT_ROOT / "data"
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--email")
    parser.add_argument(
        "--password-env",
        default="BOOTSTRAP_ADMIN_PASSWORD",
        help="从指定环境变量读取密码；未设置时安全交互输入",
    )
    args = parser.parse_args()
    password = os.getenv(args.password_env)
    if password is None:
        password = getpass.getpass("Bootstrap admin password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise SystemExit("password confirmation does not match")
    user_id = bootstrap_admin(
        database=args.database,
        data_dir=args.data_dir,
        username=args.username,
        email=args.email,
        password=password,
    )
    print(f"bootstrap admin initialized: {user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

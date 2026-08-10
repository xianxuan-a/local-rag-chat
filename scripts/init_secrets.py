"""Explicitly initialize or rotate application secrets in one env file."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio
from app.core.config import production_secret_problem


SECRET_NAMES = (
    "JWT_SECRET",
    "METRICS_SCRAPE_TOKEN",
    "BACKUP_SIGNING_KEY",
    "BOOTSTRAP_SECRET",
)


def _new_secret(name: str, reserved: set[str]) -> str:
    """Generate one policy-compliant value that is unique in this env file."""

    while True:
        candidate = secrets.token_urlsafe(48)
        if candidate in reserved:
            continue
        if production_secret_problem(name, candidate) is not None:
            continue
        reserved.add(candidate)
        return candidate


def initialize_secrets(
    env_file: Path,
    *,
    rotate_all: bool = False,
) -> tuple[str, ...]:
    env_file = env_file.expanduser().resolve()
    env_file.parent.mkdir(parents=True, exist_ok=True)
    original = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    lines = original.splitlines()
    reserved = {
        value.strip()
        for line in lines
        for key, separator, value in (line.partition("="),)
        if separator and key.strip() in SECRET_NAMES and value.strip()
    }
    generated: list[str] = []
    found: set[str] = set()
    output: list[str] = []
    for line in lines:
        key, separator, value = line.partition("=")
        normalized_key = key.strip()
        if separator and normalized_key in SECRET_NAMES:
            if normalized_key in found:
                raise ValueError(
                    f"{env_file} 包含重复 Secret 键：{normalized_key}"
                )
            found.add(normalized_key)
            if rotate_all or not value.strip():
                output.append(
                    f"{normalized_key}={_new_secret(normalized_key, reserved)}"
                )
                generated.append(normalized_key)
            else:
                output.append(line)
        else:
            output.append(line)
    for name in SECRET_NAMES:
        if name not in found:
            output.append(f"{name}={_new_secret(name, reserved)}")
            generated.append(name)

    content = os.linesep.join(output).rstrip() + os.linesep
    temporary = env_file.with_name(f".{env_file.name}.init-secrets.partial")
    if temporary.exists():
        raise FileExistsError(
            f"发现遗留临时文件，请人工核对后单独处理：{temporary}"
        )
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, env_file)
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        raise
    return tuple(generated)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="显式生成或轮换 Secret；应用启动本身绝不修改 .env"
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument(
        "--rotate-all",
        action="store_true",
        help="轮换全部四项应用 Secret，不修改其他配置",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行不可逆的 Secret 轮换",
    )
    args = parser.parse_args()
    if args.rotate_all and not args.yes:
        parser.error("--rotate-all 必须同时提供 --yes")
    if args.yes and not args.rotate_all:
        parser.error("--yes 只能与 --rotate-all 一起使用")
    generated = initialize_secrets(
        args.env_file,
        rotate_all=args.rotate_all,
    )
    if generated:
        action = "rotated" if args.rotate_all else "generated"
        print(action + ": " + ", ".join(generated))
    else:
        print("all required secrets already exist; no values changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

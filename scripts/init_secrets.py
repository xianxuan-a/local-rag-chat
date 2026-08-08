"""Explicitly generate missing application secrets in one chosen env file."""

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


def initialize_secrets(env_file: Path) -> tuple[str, ...]:
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
            found.add(normalized_key)
            if not value.strip():
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
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, env_file)
    return tuple(generated)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="显式生成缺失 Secret；应用启动本身绝不修改 .env"
    )
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    generated = initialize_secrets(args.env_file)
    if generated:
        print("generated: " + ", ".join(generated))
    else:
        print("all required secrets already exist; no values changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

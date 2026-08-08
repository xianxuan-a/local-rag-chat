"""Create an allowlisted production-candidate manifest for one commit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re


SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_CHECKS = (
    "dashscope_staging",
    "deterministic_real_e2e",
    "recovery_drill",
    "production_images",
)


def build_evidence(
    *,
    commit_sha: str,
    repository: str,
    checks: dict[str, str],
) -> dict[str, object]:
    if not SHA_PATTERN.fullmatch(commit_sha):
        raise ValueError("commit SHA must be 40 lowercase hexadecimal characters")
    if set(checks) != set(REQUIRED_CHECKS):
        raise ValueError("release evidence checks are incomplete")
    failed = [name for name, result in checks.items() if result != "passed"]
    if failed:
        raise ValueError("production candidate blocked by: " + ", ".join(failed))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must use owner/name form")

    return {
        "schema_version": 1,
        "commit_sha": commit_sha,
        "production_candidate": True,
        "checks": {name: checks[name] for name in REQUIRED_CHECKS},
        "images": {
            "backend": f"local-rag-chat:{commit_sha}",
            "frontend": f"local-rag-chat-frontend:{commit_sha}",
        },
        "source": f"https://github.com/{repository}/commit/{commit_sha}",
        "artifact_allowlist": [
            "release-manifest.json",
            "python-dependencies.txt",
            "node-dependencies.json",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument(
        "--repository",
        default=os.getenv("GITHUB_REPOSITORY", "xianxuan-a/local-rag-chat"),
    )
    for name in REQUIRED_CHECKS:
        parser.add_argument(f"--{name.replace('_', '-')}", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    checks = {
        name: getattr(arguments, name)
        for name in REQUIRED_CHECKS
    }
    evidence = build_evidence(
        commit_sha=arguments.commit_sha,
        repository=arguments.repository,
        checks=checks,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"production_candidate=PASS commit_sha={arguments.commit_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

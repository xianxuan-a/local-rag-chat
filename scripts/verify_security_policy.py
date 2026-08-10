"""Fail closed when a dependency-audit exception is invalid or expired."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "security" / "pip-audit-policy.json"
LOCK_PATH = PROJECT_ROOT / "requirements.lock"
MAX_EXCEPTION_DAYS = 30


def verify_policy(*, today: date | None = None) -> list[str]:
    current_date = today or date.today()
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 2:
        raise ValueError("unsupported security policy schema")
    exceptions = policy.get("exceptions")
    if not isinstance(exceptions, list):
        raise ValueError("security policy exceptions must be a list")

    lock_lines = {
        line.strip().lower()
        for line in LOCK_PATH.read_text(encoding="utf-8").splitlines()
        if "==" in line
    }
    identifiers: list[str] = []
    for item in exceptions:
        if not isinstance(item, dict):
            raise ValueError("security policy exception must be an object")
        identifier = str(item.get("id", "")).strip()
        package = str(item.get("package", "")).strip().lower()
        version = str(item.get("version", "")).strip()
        reason = str(item.get("reason", "")).strip()
        tracking = str(item.get("tracking", "")).strip()
        owner = str(item.get("owner", "")).strip()
        severity = str(item.get("severity", "")).strip().lower()
        if not identifier or identifier in identifiers:
            raise ValueError("security policy IDs must be present and unique")
        if f"{package}=={version}" not in lock_lines:
            raise ValueError(f"{identifier} does not match requirements.lock")
        if (
            len(reason) < 80
            or not tracking.startswith("https://")
            or owner != "repository-maintainers"
            or severity != "critical"
        ):
            raise ValueError(f"{identifier} lacks a reviewable mitigation")
        approved = date.fromisoformat(str(item.get("approved_on", "")))
        review = date.fromisoformat(str(item.get("review_on", "")))
        expires = date.fromisoformat(str(item.get("expires_on", "")))
        if expires <= current_date:
            raise ValueError(f"{identifier} security exception has expired")
        if review <= current_date:
            raise ValueError(f"{identifier} security exception requires review")
        if review <= approved or review > expires:
            raise ValueError(f"{identifier} has an invalid review window")
        if (expires - approved).days > MAX_EXCEPTION_DAYS:
            raise ValueError(f"{identifier} exception exceeds {MAX_EXCEPTION_DAYS} days")
        identifiers.append(identifier)
    return identifiers


def main() -> int:
    identifiers = verify_policy()
    print("security_policy=PASS")
    print("audited_exceptions=" + ",".join(identifiers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

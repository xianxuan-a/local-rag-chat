"""Strict helpers for handling user-supplied filenames and directories."""

from collections.abc import Iterable
from pathlib import Path, PurePosixPath, PureWindowsPath
import re


_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def sanitize_filename(filename: str) -> str:
    """Validate and normalize a single safe filename.

    Directory components are rejected rather than silently discarded so that a
    path-traversal attempt can never be reinterpreted as a legitimate basename.
    """
    if not isinstance(filename, str):
        raise ValueError("文件名必须是字符串")

    normalized = filename.strip()
    if not normalized:
        raise ValueError("文件名不能为空")
    if len(normalized) > 255:
        raise ValueError("文件名不能超过 255 个字符")
    if normalized in {".", ".."} or ".." in normalized:
        raise ValueError("文件名不能包含 '..'")
    if "/" in normalized or "\\" in normalized:
        raise ValueError("文件名不能包含目录分量")

    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(normalized)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("文件名不能是绝对路径")
    if _INVALID_WINDOWS_CHARS.search(normalized):
        raise ValueError("文件名包含非法字符")
    if normalized.endswith((".", " ")):
        raise ValueError("文件名不能以点或空格结尾")

    windows_stem = normalized.split(".", maxsplit=1)[0].upper()
    if windows_stem in _WINDOWS_RESERVED_NAMES:
        raise ValueError("文件名是 Windows 保留名称")
    return normalized


def get_file_extension(filename: str) -> str:
    """Return a validated filename's lowercase extension, including the dot."""
    safe_name = sanitize_filename(filename)
    return Path(safe_name).suffix.lower()


def validate_file_extension(filename: str, allowed_extensions: Iterable[str]) -> str:
    """Return the normalized extension or raise for an unsupported file type."""
    extension = get_file_extension(filename)
    normalized_allowed = {
        item.lower() if item.startswith(".") else f".{item.lower()}"
        for item in allowed_extensions
    }
    if not extension or extension not in normalized_allowed:
        raise ValueError(f"不支持的文件扩展名：{extension or '无扩展名'}")
    return extension


def ensure_directory(directory: str | Path) -> Path:
    """Create a directory idempotently and return its resolved path."""
    path = Path(directory).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise NotADirectoryError(f"目标不是目录：{path}")
    return path

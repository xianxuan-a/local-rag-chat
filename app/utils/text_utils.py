"""Small, deterministic text helpers."""

import re


_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Trim text and collapse consecutive whitespace to one space."""
    return _WHITESPACE.sub(" ", text).strip()


def truncate_text(text: str, max_length: int, suffix: str = "…") -> str:
    """Truncate text without exceeding ``max_length`` characters."""
    if max_length < 0:
        raise ValueError("max_length 不能小于 0")
    if len(text) <= max_length:
        return text
    if max_length == 0:
        return ""
    if len(suffix) >= max_length:
        return suffix[:max_length]
    return f"{text[: max_length - len(suffix)]}{suffix}"


def estimate_text_length(text: str) -> int:
    """Return a deterministic character-count estimate."""
    return len(text)

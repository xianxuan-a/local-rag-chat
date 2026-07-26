"""Small, deterministic text helpers."""

import re


_WHITESPACE = re.compile(r"\s+")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\n]+")


def clean_text(text: str) -> str:
    """Remove deterministic noise while preserving paragraph boundaries."""
    if not isinstance(text, str):
        raise TypeError("text 必须是字符串")

    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    normalized = _CONTROL_CHARACTERS.sub("", normalized)

    cleaned_lines: list[str] = []
    previous_was_blank = False
    for raw_line in normalized.split("\n"):
        line = _HORIZONTAL_WHITESPACE.sub(" ", raw_line).strip()
        if not line:
            if cleaned_lines and not previous_was_blank:
                cleaned_lines.append("")
            previous_was_blank = True
            continue
        cleaned_lines.append(line)
        previous_was_blank = False

    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()
    return "\n".join(cleaned_lines)


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

"""Deterministic filtering for instructions embedded in untrusted evidence."""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.utils.text_utils import clean_text


_INJECTION_PATTERNS = (
    re.compile(
        r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|system)"
        r"\b.{0,30}\b(instruction|prompt|message)s?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(system|developer)\s+(prompt|message|instruction)s?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(reveal|print|show|leak|expose)\b.{0,50}"
        r"\b(prompt|secret|api[ _-]?key|environment variable|credential)s?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(call|invoke|execute|run|use)\b.{0,30}"
        r"\b(tool|function|shell|command|browser|url)\b",
        re.IGNORECASE,
    ),
    re.compile(r"忽略.{0,20}(之前|以上|系统).{0,20}(指令|提示词|消息)"),
    re.compile(r"(泄露|显示|输出|打印).{0,30}(系统提示词|密钥|环境变量|凭据)"),
    re.compile(r"(调用|执行|运行|使用).{0,20}(工具|函数|命令|脚本|网址)"),
    re.compile(r"(扮演|你现在是|切换角色).{0,40}(系统|开发者|管理员)"),
)


@dataclass(frozen=True, slots=True)
class ContentSanitizationResult:
    """Safe evidence text plus auditable exclusion reasons."""

    content: str
    excluded_reasons: tuple[str, ...]
    suspicious_segment_count: int


class UntrustedContentSanitizer:
    """Remove suspicious blocks without treating evidence as instructions."""

    def sanitize(self, content: str) -> ContentSanitizationResult:
        normalized = clean_text(content)
        if not normalized:
            return ContentSanitizationResult("", ("empty_content",), 0)
        blocks = [
            block.strip()
            for block in re.split(r"(?:\r?\n){2,}", normalized)
            if block.strip()
        ]
        if len(blocks) == 1:
            blocks = [
                block.strip()
                for block in re.split(r"(?<=[。！？.!?])\s+", normalized)
                if block.strip()
            ]
        safe: list[str] = []
        suspicious = 0
        for block in blocks:
            if any(pattern.search(block) for pattern in _INJECTION_PATTERNS):
                suspicious += 1
                continue
            safe.append(block)
        cleaned = clean_text("\n\n".join(safe))
        reasons: list[str] = []
        if suspicious:
            reasons.append("prompt_injection_segment_removed")
        if not cleaned:
            reasons.append("no_safe_content")
        return ContentSanitizationResult(
            content=cleaned,
            excluded_reasons=tuple(reasons),
            suspicious_segment_count=suspicious,
        )

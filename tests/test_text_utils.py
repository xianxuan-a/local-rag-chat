"""Deterministic text-cleaning tests."""

from app.utils.text_utils import clean_text, normalize_text


def test_clean_text_normalizes_noise_and_preserves_paragraphs() -> None:
    raw = "\ufeff  第一段\t内容  \r\n\r第二行\x00\r\n \r\n\r\n第三段：中文, English 123!  "

    assert clean_text(raw) == (
        "第一段 内容\n\n第二行\n\n第三段：中文, English 123!"
    )


def test_clean_text_is_stable_and_can_return_empty() -> None:
    raw = " \t\r\n\x00\x07 \n "

    assert clean_text(raw) == ""
    assert clean_text(raw) == clean_text(raw)


def test_existing_normalize_text_contract_is_unchanged() -> None:
    assert normalize_text(" first\n\nsecond\tvalue ") == "first second value"

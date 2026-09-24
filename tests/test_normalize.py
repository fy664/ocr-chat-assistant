"""Text normalization tests (whitespace, newlines, punctuation, noise)."""
from __future__ import annotations

from app.ocr.normalize import (
    collapse_repeated_punctuation,
    collapse_whitespace,
    count_effective_chars,
    normalize_line,
    normalize_text,
)


def test_whitespace_collapse():
    assert collapse_whitespace("你 好   吗") == "你 好 吗"
    assert collapse_whitespace("  你好  ") == "你好"


def test_newlines_become_spaces():
    # spec example: "你 好   吗\n\n\n" -> "你 好 吗"
    assert normalize_text("你 好   吗\n\n\n") == "你 好 吗"


def test_repeated_punctuation():
    assert collapse_repeated_punctuation("你好！！！") == "你好！"
    assert collapse_repeated_punctuation("真的？？？") == "真的？"
    assert collapse_repeated_punctuation("好的。。。") == "好的。"


def test_punctuation_noise_not_a_change():
    # OCR jitter: "你好！" vs "你好 ！" must normalize to the same fingerprint
    assert normalize_text("你好！") == normalize_text("你好 ！")


def test_empty_string():
    assert normalize_text("") == ""
    assert normalize_text("   \n\n  ") == ""


def test_border_noise_stripped():
    assert normalize_line("|你好|") == "你好"
    assert normalize_line("·你好·") == "你好"


def test_noise_only_lines_dropped():
    assert normalize_text("……\n---\n你好") == "你好"


def test_count_effective_chars():
    assert count_effective_chars("你好") == 2
    assert count_effective_chars("!!") == 0
    assert count_effective_chars("hello") == 5


def test_fingerprint_stability():
    from app.ocr.diff import fingerprint

    assert fingerprint(normalize_text("你好！")) == fingerprint(normalize_text("你好 ！"))
    assert fingerprint(normalize_text("你好")) != fingerprint(normalize_text("你好吗"))

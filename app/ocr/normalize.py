"""Text normalization for change detection.

Purpose: tiny OCR noise (extra whitespace, repeated punctuation) must NOT
trigger an LLM call, so normalization is applied before fingerprinting.
It intentionally does not over-modify the original text.
"""
from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_REPEATED_PUNCT_RE = re.compile(r"([!！?？。.…，,、;；:：~～]){2,}")
_PUNCT_CHARS = "!！?？。.…，,、;；:：~～"
_SPACE_AROUND_PUNCT_RE = re.compile(
    rf"\s*([{_PUNCT_CHARS}])\s*"
)
_BORDER_NOISE = "|丨·•―_—–"


def collapse_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def collapse_repeated_punctuation(text: str) -> str:
    return _REPEATED_PUNCT_RE.sub(lambda m: m.group(0)[0], text)


def strip_space_around_punctuation(text: str) -> str:
    """Remove whitespace adjacent to punctuation ("你好 ！" -> "你好！"),
    so tiny OCR spacing jitter never changes the fingerprint (spec 14).
    Applies before collapsing repeated punctuation so "你 好 ！ ！"
    normalizes to "你 好！"."""
    return _SPACE_AROUND_PUNCT_RE.sub(r"\1", text)


def _strip_border_noise(line: str) -> str:
    return line.strip(_BORDER_NOISE).strip()


def _is_noise_line(line: str) -> bool:
    for ch in line:
        if ch.isalnum() or "一" <= ch <= "鿿":
            return False
    return True


def normalize_line(raw_line: str) -> str:
    """Normalize one OCR line (kept close to the original)."""
    line = unicodedata.normalize("NFKC", raw_line)
    line = collapse_whitespace(line)
    line = _strip_border_noise(line)
    line = strip_space_around_punctuation(line)
    line = collapse_repeated_punctuation(line)
    return line


def normalize_text(text: str) -> str:
    """Normalize a whole OCR snapshot into one fingerprintable string.

    "你 好   吗\\n\\n\\n" -> "你 好 吗"
    """
    if not text:
        return ""
    lines = []
    for raw_line in text.splitlines():
        line = normalize_line(raw_line)
        if line and not _is_noise_line(line):
            lines.append(line)
    return " ".join(lines)


def count_effective_chars(text: str) -> int:
    """Count of meaningful characters (alnum / CJK)."""
    return sum(1 for ch in text if ch.isalnum() or "一" <= ch <= "鿿")

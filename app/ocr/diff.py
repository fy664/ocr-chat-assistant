"""Change detection over normalized OCR text (fingerprint based).

Three outcomes:
  SAME        - fingerprint identical -> discard
  SCROLL_ONLY - visible line multiset is a strict subset of the previous
                snapshot's (pure scroll-up, no new content) -> update
                display/context but do NOT trigger the LLM
  CHANGED     - new content -> debounce -> analysis

Repeated LLM calls for scroll-cycling are prevented by the
`is_current_analyzed` fingerprint dedup applied at debounce time: any
exact view that was already analyzed is skipped even when it reappears.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from enum import Enum, auto

from app.ocr.normalize import normalize_text


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ChangeKind(Enum):
    SAME = auto()
    SCROLL_ONLY = auto()
    CHANGED = auto()


class TextDiffTracker:
    """Tracks last seen / last analyzed fingerprints plus the visible line multiset."""

    def __init__(self) -> None:
        self._last_fp: str | None = None
        self._last_analyzed_fp: str | None = None
        self._last_counts: Counter = Counter()

    @property
    def last_fingerprint(self) -> str | None:
        return self._last_fp

    def update(self, text: str, lines=None) -> ChangeKind:
        """Register the latest snapshot. `lines` may be a list of OCRLine or str."""
        fp = fingerprint(text)
        if fp == self._last_fp:
            return ChangeKind.SAME
        self._last_fp = fp

        new_counts = self._line_counts(lines)
        if (
            new_counts
            and self._last_counts
            and all(new_counts.get(k, 0) <= self._last_counts.get(k, 0) for k in new_counts)
        ):
            # every visible line was already visible (pure scroll-up)
            self._last_counts = new_counts
            return ChangeKind.SCROLL_ONLY

        self._last_counts = new_counts
        return ChangeKind.CHANGED

    @staticmethod
    def _line_counts(lines) -> Counter:
        counts: Counter = Counter()
        if not lines:
            return counts
        for line in lines:
            text = getattr(line, "text", None)
            if text is None:
                text = line
            norm = normalize_text(str(text))
            if norm:
                counts[norm] += 1
        return counts

    def mark_analyzed(self, text: str) -> None:
        self._last_analyzed_fp = fingerprint(text)

    def mark_analyzed_by_fp(self, fp: str) -> None:
        self._last_analyzed_fp = fp

    def is_current_analyzed(self, text: str) -> bool:
        return fingerprint(text) == self._last_analyzed_fp

    def reset(self) -> None:
        self._last_fp = None
        self._last_analyzed_fp = None
        self._last_counts = Counter()

    def reset_baseline(self, current_text: str | None) -> None:
        """After 'clear context': baseline = current snapshot, nothing analyzed."""
        self._last_fp = fingerprint(current_text) if current_text else None
        self._last_analyzed_fp = None
        self._last_counts = Counter()

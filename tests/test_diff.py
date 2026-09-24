"""Diff tests: same/different text, OCR noise, real new message, scroll, dedup."""
from __future__ import annotations

from app.ocr.diff import ChangeKind, TextDiffTracker
from app.ocr.normalize import normalize_text


def _lines(*texts: str) -> list[str]:
    return list(texts)


def test_same_text_no_change():
    tracker = TextDiffTracker()
    assert tracker.update("你好") == ChangeKind.CHANGED   # first observation
    assert tracker.update("你好") == ChangeKind.SAME      # identical -> no change


def test_different_text_changes():
    tracker = TextDiffTracker()
    tracker.update("你好")
    assert tracker.update("你好吗") == ChangeKind.CHANGED


def test_tiny_ocr_noise_not_a_change():
    tracker = TextDiffTracker()
    tracker.update(normalize_text("你好！"), _lines("你好！"))
    assert tracker.update(normalize_text("你好 ！"), _lines("你好 ！")) == ChangeKind.SAME


def test_real_new_message_is_change():
    tracker = TextDiffTracker()
    tracker.update(normalize_text("你好！"), _lines("你好！"))
    assert tracker.update(normalize_text("你好！\n你周末有空吗"),
                          _lines("你好！", "你周末有空吗")) == ChangeKind.CHANGED


def test_pure_scroll_is_scroll_only():
    tracker = TextDiffTracker()
    tracker.update("A B C", _lines("A", "B", "C"))
    # scrolled up: C no longer visible, nothing new
    assert tracker.update("A B", _lines("A", "B")) == ChangeKind.SCROLL_ONLY
    # scrolled down again: content re-added (dedup at analysis time prevents repeats)
    assert tracker.update("A B C", _lines("A", "B", "C")) == ChangeKind.CHANGED


def test_scroll_plus_new_message_is_change():
    tracker = TextDiffTracker()
    tracker.update("A B C", _lines("A", "B", "C"))
    assert tracker.update("B C D", _lines("B", "C", "D")) == ChangeKind.CHANGED


def test_already_analyzed_dedup():
    tracker = TextDiffTracker()
    tracker.update("你好", _lines("你好"))
    assert tracker.is_current_analyzed("你好") is False
    tracker.mark_analyzed("你好")
    assert tracker.is_current_analyzed("你好") is True
    assert tracker.is_current_analyzed("你好吗") is False


def test_scroll_back_not_reanalyzed():
    tracker = TextDiffTracker()
    tracker.update("A", _lines("A"))
    tracker.mark_analyzed("A")
    tracker.update("B", _lines("B"))
    tracker.update("A", _lines("A"))      # scrolled back
    assert tracker.is_current_analyzed("A") is True


def test_reset():
    tracker = TextDiffTracker()
    tracker.update("A", _lines("A"))
    tracker.mark_analyzed("A")
    tracker.reset()
    assert tracker.update("A") == ChangeKind.CHANGED
    assert tracker.is_current_analyzed("A") is False


def test_reset_baseline():
    tracker = TextDiffTracker()
    tracker.update("A", _lines("A"))
    tracker.mark_analyzed("A")
    tracker.reset_baseline("A")
    assert tracker.update("A") == ChangeKind.SAME        # baseline is not new
    assert tracker.is_current_analyzed("A") is False     # nothing analyzed yet

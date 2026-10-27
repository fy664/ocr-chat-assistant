"""Tests for the fast frame gate."""
from __future__ import annotations

import numpy as np

from app.capture.frame_gate import FrameGate


def test_identical_frames_are_skipped_and_changes_pass():
    gate = FrameGate(max_skips=3)
    frame = np.zeros((60, 90, 3), dtype=np.uint8)
    assert gate.is_duplicate(frame) is False
    assert gate.is_duplicate(frame.copy()) is True
    changed = frame.copy()
    changed[10, 10, 0] = 255
    assert gate.is_duplicate(changed) is False
    assert gate.skipped == 1


def test_gate_forces_ocr_after_max_skips():
    gate = FrameGate(max_skips=2)
    frame = np.full((20, 30, 3), 7, dtype=np.uint8)
    assert gate.is_duplicate(frame) is False
    assert gate.is_duplicate(frame.copy()) is True
    assert gate.is_duplicate(frame.copy()) is True
    # after two skips the third identical frame is processed again
    assert gate.is_duplicate(frame.copy()) is False


def test_missing_frames_are_never_skipped():
    gate = FrameGate()
    assert gate.is_duplicate(None) is False
    assert gate.is_duplicate(np.zeros((10, 10, 3), dtype=np.uint8)) is False
    assert gate.is_duplicate(None) is False


def test_reset_clears_previous_hash():
    gate = FrameGate()
    frame = np.ones((10, 10, 3), dtype=np.uint8)
    assert gate.is_duplicate(frame) is False
    gate.reset()
    assert gate.is_duplicate(frame) is False

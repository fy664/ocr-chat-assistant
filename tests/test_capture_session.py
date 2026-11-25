"""Tests for the continuous capture session (sampling, direction, pause)."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from app.analysis.capture_session import (
    STATE_ARMED,
    STATE_COLLECTING,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_STOPPING,
    CaptureSession,
)
from app.capture.scroll_signal import ShiftEstimate, VerticalShiftEstimator
from app.capture.window_guard import ForegroundGuard
from app.models.schemas import ScreenshotFrame

REGION = {"x": 100, "y": 200, "width": 400, "height": 300}


def region():
    from app.models.schemas import ScreenRegion

    return ScreenRegion(**REGION)


class FakeMonitor(QObject):
    """Stand-in for RegionMonitor; tests emit frames by hand."""

    frame_captured = Signal(object)
    capture_error = Signal(str)

    def __init__(self, region=None, interval_ms=0, parent=None):
        super().__init__(parent)
        self.region = region
        self.interval_ms = interval_ms
        self.started = False
        self.closed = False

    def start(self, region=None):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True
        self.started = False


class FakeGuard:
    def __init__(self, ok=True, reason=""):
        self.ok = ok
        self.reason = reason
        self.calls = 0

    def check(self, region):
        self.calls += 1
        return self.ok, self.reason


class FakeEstimator:
    def __init__(self, estimates=None):
        self.estimates = list(estimates or [])
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1

    def update(self, image):
        if not self.estimates:
            return None
        return self.estimates.pop(0)


class FakeCapture:
    def __init__(self, frame=None):
        self.frame = frame
        self.calls = 0

    def capture(self, region):
        self.calls += 1
        return self.frame


def frame(tag=0, image=None):
    return ScreenshotFrame(
        x=REGION["x"], y=REGION["y"], width=REGION["width"], height=REGION["height"],
        timestamp=float(tag), image=image,
    )


def build(**kwargs):
    monitor = kwargs.pop("monitor", None) or FakeMonitor()
    session = CaptureSession(region(), monitor=monitor, **kwargs)
    return session, monitor


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------

def test_first_frame_is_forwarded_without_a_direction(qapp):
    session, monitor = build(guard=FakeGuard(), estimator=FakeEstimator())
    states, frames = [], []
    session.state_changed.connect(states.append)
    session.frame_ready.connect(lambda f, d: frames.append((f.timestamp, d)))
    session.start()
    assert monitor.started
    assert states[-1] == STATE_COLLECTING

    monitor.frame_captured.emit(frame(1))
    assert frames == [(1.0, 0)]     # direction unknown: stitcher treats it as page 1
    assert session.counters["emitted"] == 1
    session.stop()
    assert states[-1] == STATE_STOPPING


def test_shift_direction_is_reported_and_static_frames_are_skipped(qapp):
    monkeypatch_est = FakeEstimator([
        ShiftEstimate(-40.0, 0.9, 1),    # content up -> new messages
        ShiftEstimate(-22.0, 0.9, 1),
        ShiftEstimate(44.0, 0.9, -1),    # content down -> older history
        ShiftEstimate(0.0, 0.95, 0),     # untouched screen
    ])
    session, monitor = build(guard=FakeGuard(), estimator=monkeypatch_est)
    frames = []
    session.frame_ready.connect(lambda f, d: frames.append(d))
    session.start()
    for tag in range(1, 5):
        monitor.frame_captured.emit(frame(tag))
    assert frames == [1, 1, -1]
    assert session.counters["skipped"] == 1
    session.close()


def test_guard_failure_pauses_and_recovery_resumes(qapp):
    guard = FakeGuard(ok=True)
    session, monitor = build(guard=guard, estimator=FakeEstimator())
    states, pauses, resumes, frames = [], [], [], []
    session.state_changed.connect(states.append)
    session.paused.connect(pauses.append)
    session.resumed.connect(lambda: resumes.append(True))
    session.frame_ready.connect(lambda f, d: frames.append(f.timestamp))

    session.start()
    monitor.frame_captured.emit(frame(1))
    assert len(frames) == 1

    guard.ok, guard.reason = False, "前台窗口没有覆盖选区（可能切换了聊天窗口）"
    monitor.frame_captured.emit(frame(2))
    assert states[-1] == STATE_PAUSED
    assert pauses and "前台窗口" in pauses[-1]
    assert len(frames) == 1          # paused frames are not forwarded

    guard.ok, guard.reason = True, ""
    monitor.frame_captured.emit(frame(3))
    assert states[-1] == STATE_COLLECTING
    assert resumes
    assert frames[-1] == 3.0
    session.close()


def test_stop_during_pause_keeps_counters_and_stops_monitor(qapp):
    session, monitor = build(guard=FakeGuard(ok=False, reason="选区不在屏幕范围内（测试）"))
    session.start()
    assert session.state == STATE_PAUSED
    monitor.frame_captured.emit(frame(1))
    assert session.counters["emitted"] == 0
    session.stop()
    assert not monitor.started
    assert session.state == STATE_STOPPING
    assert monitor.closed is False
    session.close()
    assert monitor.closed


def test_capture_now_returns_one_frame(qapp):
    capture = FakeCapture(frame(9))
    session, monitor = build(guard=FakeGuard(), estimator=FakeEstimator(), capture=capture)
    session.start()
    got = session.capture_now()
    assert got is not None and got.timestamp == 9.0
    assert capture.calls == 1
    session.close()


def test_capture_now_refuses_after_the_guard_paused(qapp):
    """A paused session must not grab "one last frame" of whatever is in front.

    The user's report: the window check had already refused to collect, yet
    clicking 结束采集 still captured a frame - that one came from another
    window and its text polluted the transcript.
    """
    guard = FakeGuard(ok=True)
    capture = FakeCapture(frame(9))
    session, monitor = build(guard=guard, estimator=FakeEstimator(), capture=capture)
    errors: list[str] = []
    session.error.connect(errors.append)
    session.start()
    assert session.state == STATE_COLLECTING

    guard.ok, guard.reason = False, "前台窗口没有覆盖选区（可能切换了聊天窗口）"
    monitor.frame_captured.emit(frame(1))
    assert session.state == STATE_PAUSED

    assert session.capture_now() is None
    assert capture.calls == 0
    assert errors and "最后一帧" in errors[-1]
    session.close()


def test_capture_now_refuses_when_the_region_left_the_screen(qapp):
    """Focus is irrelevant here: the region is simply not on screen any more."""
    box = [(0, 0, 1920, 1080)]
    guard = ForegroundGuard(
        probe=lambda: (0, 0, 1920, 1080),
        bounds_probe=lambda: box[0],
    )
    capture = FakeCapture(frame(9))
    session, monitor = build(guard=guard, estimator=FakeEstimator(), capture=capture)
    errors: list[str] = []
    session.error.connect(errors.append)
    session.start()
    assert session.state == STATE_COLLECTING

    box[0] = (0, 0, 300, 300)  # resolution changed / window moved away
    assert session.capture_now() is None
    assert capture.calls == 0
    assert errors and "屏幕范围" in errors[-1]
    session.close()


def test_unexplained_scene_change_is_forwarded_not_skipped(qapp):
    """A jump produces "no direction" - that must not be read as "sit still".

    Two completely different screens correlate badly, so the estimator reports
    direction 0. Skipping that frame loses a whole screen with no trace; it has
    to reach the stitcher, which can still find an overlap or mark a breakpoint.
    """
    estimator = FakeEstimator([
        ShiftEstimate(-40.0, 0.9, 1),                 # real scroll down
        ShiftEstimate(0.0, 0.12, 0, reliable=False),  # jump: direction unknown
    ])
    session, monitor = build(guard=FakeGuard(), estimator=estimator)
    frames, hints = [], []
    session.frame_ready.connect(lambda f, d: frames.append(d))
    session.status_changed.connect(lambda snap: hints.append(snap))
    session.start()
    monitor.frame_captured.emit(frame(1))
    monitor.frame_captured.emit(frame(2))
    assert frames == [1, 0]           # the jump is forwarded, flagged unknown
    assert session.counters["skipped"] == 0
    assert session.counters["uncertain"] == 1
    session.close()


def test_confidently_static_frame_is_still_skipped(qapp):
    estimator = FakeEstimator([ShiftEstimate(-22.0, 0.9, 1), ShiftEstimate(0.0, 0.97, 0)])
    session, monitor = build(guard=FakeGuard(), estimator=estimator)
    frames = []
    session.frame_ready.connect(lambda f, d: frames.append(d))
    session.start()
    monitor.frame_captured.emit(frame(1))
    monitor.frame_captured.emit(frame(2))
    assert frames == [1]
    assert session.counters["skipped"] == 1
    assert session.counters["uncertain"] == 0
    session.close()


def test_capture_now_runs_the_same_window_check(qapp):
    """No frame was ever paused, but the check fails right now: refuse anyway."""
    guard = FakeGuard(ok=True)
    capture = FakeCapture(frame(9))
    session, monitor = build(guard=guard, estimator=FakeEstimator(), capture=capture)
    errors: list[str] = []
    session.error.connect(errors.append)
    session.start()
    assert session.state == STATE_COLLECTING

    guard.ok, guard.reason = False, "前台窗口没有覆盖选区（可能切换了聊天窗口）"
    assert session.capture_now() is None       # before: grabbed the frame anyway
    assert capture.calls == 0
    assert errors and "最后一帧" in errors[-1]
    session.close()


def test_own_window_in_front_does_not_block_the_final_frame(qapp):
    """Clicking 结束采集 makes our own window foreground; that is not a switch."""
    import os

    own = ForegroundGuard(
        probe=lambda: (0, 0, 80, 120),             # our window: small, top-left
        handle_probe=lambda: (1, os.getpid()),
        own_pid=os.getpid(),
        bounds_probe=lambda: (0, 0, 1920, 1080),
    )
    ok, reason = own.check(region())
    assert ok and reason == ""

    stranger = ForegroundGuard(
        probe=lambda: (0, 0, 80, 120),
        handle_probe=lambda: (1, os.getpid() + 1),
        own_pid=os.getpid(),
        bounds_probe=lambda: (0, 0, 1920, 1080),
    )
    ok, reason = stranger.check(region())
    assert not ok and "前台窗口没有覆盖选区" in reason


def test_own_window_over_the_region_still_blocks(qapp):
    """If our own window sits on the region, a grab would capture our UI."""
    import os

    own = ForegroundGuard(
        probe=lambda: (100, 200, 300, 400),        # overlaps the region
        handle_probe=lambda: (1, os.getpid()),
        own_pid=os.getpid(),
        bounds_probe=lambda: (0, 0, 1920, 1080),
    )
    ok, reason = own.check(region())
    assert not ok and "前台窗口没有覆盖选区" in reason


def test_double_start_is_ignored(qapp):
    session, monitor = build(guard=FakeGuard(), estimator=FakeEstimator())
    session.start()
    session.start()
    assert session.state == STATE_COLLECTING
    session.close()


# ---------------------------------------------------------------------------
# Vertical shift estimator
# ---------------------------------------------------------------------------

def _scroll_image(height=300, width=400, shift=0, seed=0):
    """A synthetic 'chat' image whose content is moved by ``shift`` pixels.

    Positive ``shift`` means the visible window starts lower in the content,
    i.e. the content moved **up** (the user scrolled down for new messages).
    Each content row has its own brightness, so the row profile is aperiodic
    and the correlation has a single unambiguous peak.
    """
    rng = np.random.default_rng(seed)
    content = np.zeros((height * 3, width), dtype=np.float32)
    row_values = rng.integers(60, 240, size=(content.shape[0],)).astype(np.float32)
    content[:] = row_values[:, None]
    content += rng.normal(0, 4, size=content.shape).astype(np.float32)
    top = height + shift
    img = np.clip(content[top:top + height, :], 0, 255).astype(np.uint8)
    return np.stack([img, img, img], axis=2)


@pytest.mark.parametrize(
    "shift,expected",
    [(40, 1), (22, 1), (-30, -1), (-44, -1)],
)
def test_estimator_recovers_direction(shift, expected):
    est = VerticalShiftEstimator()
    est.update(_scroll_image(shift=0, seed=1))
    got = est.update(_scroll_image(shift=shift, seed=1))
    assert got is not None
    assert got.direction == expected
    assert got.score > 0.8


@pytest.mark.parametrize("shift", [18, -24])
def test_estimator_keeps_signed_lag_with_downsampled_color_frames(shift):
    est = VerticalShiftEstimator(downscale=3)

    def rgba(offset):
        rgb = _scroll_image(shift=offset, seed=2).copy()
        rgb[..., 0] //= 2
        rgb[..., 2] //= 3
        alpha = np.random.default_rng(offset + 45).integers(0, 255, rgb.shape[:2], dtype=np.uint8)
        return np.dstack((rgb, alpha))

    assert est.update(rgba(0)) is None
    result = est.update(rgba(shift))
    assert result.shift_px == -shift
    assert result.direction == (1 if shift > 0 else -1)
    assert result.score == pytest.approx(1.0)


def test_estimator_reports_static_for_identical_frames():
    est = VerticalShiftEstimator()
    est.update(_scroll_image(seed=2))
    got = est.update(_scroll_image(seed=2))
    assert got is not None
    assert got.direction == 0


def test_estimator_needs_a_previous_frame():
    est = VerticalShiftEstimator()
    assert est.update(_scroll_image(seed=3)) is None


# ---------------------------------------------------------------------------
# Window guard
# ---------------------------------------------------------------------------

def test_estimator_flags_a_completely_different_screen_as_unknown():
    """Two unrelated screens must not be mistaken for "nothing moved"."""
    est = VerticalShiftEstimator()
    est.update(_scroll_image(seed=11))
    got = est.update(_scroll_image(seed=12))
    assert got is not None
    assert got.direction == 0
    assert got.reliable is False

    est = VerticalShiftEstimator()
    est.update(_scroll_image(seed=13))
    got = est.update(_scroll_image(seed=13))   # identical: same screen, noise
    assert got.direction == 0
    assert got.reliable is True


def test_guard_accepts_covering_window_and_rejects_others():
    guard = ForegroundGuard(
        probe=lambda: (0, 0, 1920, 1080),
        bounds_probe=lambda: (0, 0, 1920, 1080),
    )
    ok, reason = guard.check(region())
    assert ok and reason == ""

    guard = ForegroundGuard(
        probe=lambda: (0, 0, 400, 300),
        bounds_probe=lambda: (0, 0, 1920, 1080),
    )
    ok, reason = guard.check(region())
    assert not ok and "前台窗口没有覆盖选区" in reason


def test_guard_rejects_region_outside_the_screen():
    guard = ForegroundGuard(
        probe=lambda: (0, 0, 1920, 1080),
        bounds_probe=lambda: (0, 0, 300, 300),
    )
    ok, reason = guard.check(region())
    assert not ok and "屏幕范围" in reason


def test_guard_never_blocks_when_the_platform_is_unknown():
    guard = ForegroundGuard(probe=lambda: None, bounds_probe=lambda: None)
    ok, reason = guard.check(region())
    assert ok and reason == ""

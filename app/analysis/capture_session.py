"""Continuous scrolling capture session.

The user selects the chat region once, clicks 开始采集, then scrolls the chat
themselves. This session samples that region, skips frames that did not move,
and tells whoever listens *which way* the transcript moved:

* direction ``+1`` - new messages at the bottom (the user scrolled down);
* direction ``-1`` - older history at the top (the user scrolled up).

It also pauses automatically when the selected region is no longer the visible
chat window (another window came in front, the window moved, the screen changed)
and resumes when the chat is visible again. Pausing is reported through
``state_changed`` with a Chinese reason so the UI needs no translation table.

Nothing here touches OCR or the network; frames are only forwarded.
"""
from __future__ import annotations

from hashlib import blake2b
import logging

import numpy as np

from PySide6.QtCore import QObject, QTimer, Qt, Signal

from app.analysis.chat_layout import crop_chat_frame
from app.capture.frame_gate import FrameGate
from app.capture.monitor import RegionMonitor
from app.capture.scroll_signal import VerticalShiftEstimator
from app.capture.screen_capture import CaptureError, ScreenCapture
from app.capture.window_guard import ForegroundGuard
from app.models.schemas import ScreenRegion, ScreenshotFrame

logger = logging.getLogger("ocr_chat.capture_session")

# State labels are user facing (shown next to the buttons).
STATE_IDLE = "未采集"
STATE_ARMED = "等待滚动"
STATE_COLLECTING = "采集中"
STATE_PAUSED = "暂停"
STATE_STOPPING = "收尾"


class CaptureSession(QObject):
    state_changed = Signal(str)
    frame_ready = Signal(object, int)     # ScreenshotFrame, direction (+1 down / -1 up)
    preview_ready = Signal(object)       # pixels for local display, or None when unavailable
    paused = Signal(str)                  # reason shown in the status strip
    resumed = Signal()
    error = Signal(str)
    source_ended = Signal(str)
    status_changed = Signal(dict)         # counters snapshot

    def __init__(
        self,
        region: ScreenRegion,
        *,
        interval_ms: int = 700,
        preview_interval_ms: int = 0,
        guard=None,
        estimator: VerticalShiftEstimator | None = None,
        gate: FrameGate | None = None,
        monitor=None,
        capture=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._region = region
        self._state = STATE_IDLE
        self._guard = guard or ForegroundGuard()
        self._estimator = estimator or VerticalShiftEstimator()
        # max_skips huge => is_duplicate() becomes a pure exact-duplicate test:
        # continuous capture must never "force" an unchanged frame through.
        self._gate = gate or FrameGate(max_skips=999)
        self._capture = capture or ScreenCapture()
        self._monitor = monitor or RegionMonitor(region, interval_ms=interval_ms, capture=self._capture)
        self._monitor.frame_captured.connect(self._on_frame)
        self._monitor.capture_error.connect(self._on_capture_error)
        self._preview_timer = QTimer(self)
        self._preview_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._preview_timer.setInterval(preview_interval_ms)
        self._preview_timer.timeout.connect(self._poll_preview)
        self._read_window_preview = getattr(self._capture, "preview_frame", None)
        self._counters = {
            "frames": 0,
            "skipped": 0,
            "emitted": 0,
            "pauses": 0,
            "uncertain": 0,
        }
        self._reason = ""
        self._chat_bounds = None
        self._last_header = None

    # ---- properties -------------------------------------------------------

    @property
    def region(self) -> ScreenRegion:
        return self._region

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state in (STATE_ARMED, STATE_COLLECTING, STATE_PAUSED)

    @property
    def counters(self) -> dict:
        return dict(self._counters)

    @property
    def reason(self) -> str:
        return self._reason

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Begin sampling. The first frame decides whether we can collect."""
        if self._state != STATE_IDLE:
            return
        self._estimator.reset()
        self._gate.reset()
        self._state = STATE_ARMED
        self.state_changed.emit(STATE_ARMED)
        self._monitor.start(self._region)
        ok, reason = self._guard.check(self._region)
        if ok:
            self._set_collecting()
        else:
            self._pause(reason)
        if self._preview_timer.interval() and self.is_active:
            self._preview_timer.start()
            self._poll_preview()
        logger.info("capture session started: %s", self._region.mss_box)

    def stop(self) -> None:
        """Stop sampling; OCR may still be draining."""
        if self._state in (STATE_IDLE, STATE_STOPPING):
            return
        self._preview_timer.stop()
        self._monitor.stop()
        self.preview_ready.emit(None)
        self._state = STATE_STOPPING
        self.state_changed.emit(STATE_STOPPING)
        self._emit_status()
        logger.info("capture session stopped: %s", self._counters)

    def close(self) -> None:
        self.stop()
        try:
            self._monitor.close()
        except Exception:  # pragma: no cover - fake monitors may not implement it
            pass

    def capture_now(self) -> ScreenshotFrame | None:
        """Grab the current screen once (used for the final frame).

        Runs the **same** window validation as the periodic ticks, so a region
        that has been taken over by another window never contributes pixels.
        The one case that used to make this impossible is solved by identity
        rather than by skipping the check: clicking 结束采集 puts our own
        window in front, and :class:`ForegroundGuard` accepts that when our
        window does not overlap the region (see ``_own_window_in_front``).
        """
        if self._state == STATE_PAUSED or self._reason:
            self.error.emit(
                f"未补采最后一帧：{self._reason or '选区已失效'}（结果可能缺少最后看见的内容）"
            )
            return None
        ok, reason = self._guard.check(self._region)
        if not ok:
            self.error.emit(f"未补采最后一帧：{reason}（结果可能缺少最后看见的内容）")
            return None
        try:
            return self._capture.capture(self._region)
        except Exception as exc:
            self.error.emit(f"截取画面失败：{exc}")
            return None

    def final_frame_direction(self, frame: ScreenshotFrame) -> int:
        estimate = self._estimator.update(crop_chat_frame(frame.image, self._chat_bounds))
        return estimate.direction if estimate is not None else 0

    # ---- frame handling ---------------------------------------------------

    def _poll_preview(self) -> None:
        if not self.is_active:
            return
        try:
            if self._read_window_preview is not None:
                image = self._read_window_preview(self._region)
            else:
                ok, reason = self._guard.check(self._region)
                if not ok:
                    raise CaptureError(reason)
                image = self._capture.capture(self._region).image
        except CaptureError as exc:
            self._pause_for_source(str(exc))
            return
        if self._state == STATE_PAUSED:
            self._set_collecting()
            self._emit_status()
        if image is not None:
            self.preview_ready.emit(image)

    def _pause_for_source(self, reason: str) -> None:
        if self._state != STATE_PAUSED or self._reason != reason:
            self._pause(reason)
            self._emit_status()
        if getattr(self._capture, "ended", False):
            self.source_ended.emit(reason)

    def _on_capture_error(self, message: str) -> None:
        if not self.is_active:
            return
        ok, reason = self._guard.check(self._region)
        if not ok:
            self._pause_for_source(reason)
        else:
            self.error.emit(message)

    def set_chat_bounds(self, bounds) -> None:
        if self._chat_bounds is None and bounds:
            self._chat_bounds = bounds
            self._gate.reset()
            self._estimator.reset()

    def _on_frame(self, frame: ScreenshotFrame) -> None:
        if self._state in (STATE_IDLE, STATE_STOPPING):
            return
        self._counters["frames"] += 1

        ok, reason = self._guard.check(self._region)
        if not ok:
            self._pause(reason)
            self._emit_status()
            return
        if self._state == STATE_PAUSED:
            self._set_collecting()

        image = crop_chat_frame(frame.image, self._chat_bounds)
        changed_header = False
        if self._chat_bounds and frame.image is not None:
            height, width = frame.image.shape[:2]
            x, y, _, _ = self._chat_bounds
            header = np.ascontiguousarray(frame.image[:round(y * height), int(x * width):round((x + (1 - x) * .55) * width)])
            fingerprint = blake2b(header, digest_size=12).digest()
            changed_header = self._last_header is not None and fingerprint != self._last_header
            self._last_header = fingerprint
        if self._gate.is_duplicate(image) and not changed_header:
            self._counters["skipped"] += 1
            self._emit_status()
            return

        estimate = self._estimator.update(image)
        if estimate is not None and estimate.direction == 0 and not changed_header:
            if getattr(estimate, "reliable", True):
                # Confidently unchanged (blinking caret, hover highlight):
                # nothing new to OCR and the direction would be a guess.
                self._counters["skipped"] += 1
                self._emit_status()
                return
            # "No direction, and no proof of it" - typically a big jump or a
            # scene cut. Skipping here would silently lose a whole screen, so
            # forward it as direction-unknown and let the stitcher decide
            # (overlap -> merge, otherwise -> breakpoint).
            self._counters["uncertain"] += 1
            logger.info("frame has an unreliable shift estimate: forwarding as unknown")

        direction = 0 if estimate is None else estimate.direction
        if estimate is None:
            # First frame: no previous image to compare with. The stitcher
            # treats the first page as the document regardless of direction.
            direction = 0
        self._counters["emitted"] += 1
        self.frame_ready.emit(frame, direction)
        self._emit_status()

    # ---- state helpers ----------------------------------------------------

    def _set_collecting(self) -> None:
        self._state = STATE_COLLECTING
        self._reason = ""
        self.state_changed.emit(STATE_COLLECTING)
        self.resumed.emit()

    def _pause(self, reason: str) -> None:
        if self._state != STATE_PAUSED:
            self._state = STATE_PAUSED
            self._counters["pauses"] += 1
            self.preview_ready.emit(None)
            self.state_changed.emit(STATE_PAUSED)
        elif self._reason == reason:
            return
        self._reason = reason
        self.paused.emit(reason)
        logger.info("capture paused: %s", reason)

    def _emit_status(self) -> None:
        snapshot = dict(self._counters)
        snapshot["state"] = self._state
        snapshot["reason"] = self._reason
        self.status_changed.emit(snapshot)

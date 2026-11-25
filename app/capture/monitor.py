"""Region monitor: periodic capture of the selected region.

Capture itself (mss grab) is a millisecond-range operation and runs on the
timer thread context of the GUI loop; heavy work (OCR/LLM) is always
dispatched to worker threads by the scheduler.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from app.capture.screen_capture import ScreenCapture
from app.models.schemas import ScreenRegion, ScreenshotFrame

logger = logging.getLogger("ocr_chat.monitor")


class RegionMonitor(QObject):
    frame_captured = Signal(object)  # ScreenshotFrame
    capture_error = Signal(str)

    def __init__(
        self,
        region: ScreenRegion | None = None,
        interval_ms: int = 2000,
        parent=None,
        *,
        capture=None,
    ) -> None:
        super().__init__(parent)
        self._region = region
        self._capture = capture if capture is not None else ScreenCapture()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    @property
    def region(self) -> ScreenRegion | None:
        return self._region

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self, region: ScreenRegion | None = None) -> None:
        if region is not None:
            self._region = region
        if self._region is None:
            logger.warning("monitor start requested without a region")
            return
        self._timer.start()
        logger.info("monitor started: region=%s interval=%sms", self._region.mss_box, self._timer.interval())

    def stop(self) -> None:
        self._timer.stop()
        logger.info("monitor stopped")

    def set_interval(self, interval_ms: int) -> None:
        self._timer.setInterval(interval_ms)

    def set_region(self, region: ScreenRegion) -> None:
        self._region = region

    def _tick(self) -> None:
        if self._region is None:
            return
        try:
            frame: ScreenshotFrame = self._capture.capture(self._region)
            self.frame_captured.emit(frame)
        except Exception as exc:
            self.capture_error.emit(str(exc))

    def close(self) -> None:
        self.stop()
        self._capture.close()

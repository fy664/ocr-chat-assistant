"""Screen capture via mss.

Screenshots live in memory only: mss returns a raw buffer, we convert it to
a numpy RGB array and never write anything to disk.
Coordinates are *physical* pixels (mss virtual-desktop space, supports
negative origins on multi-monitor setups).
"""
from __future__ import annotations

import logging

from app.models.schemas import ScreenRegion, ScreenshotFrame
from app.utils.time import now_ts

logger = logging.getLogger("ocr_chat.capture")


class CaptureError(RuntimeError):
    pass


class ScreenCapture:
    def __init__(self) -> None:
        import mss

        self._mss = mss
        self._sct = self._mss.mss()

    def capture(self, region: ScreenRegion, timestamp: float | None = None) -> ScreenshotFrame:
        try:
            shot = self._sct.grab(region.mss_box)
        except Exception as exc:
            raise CaptureError(f"截图失败: {exc}") from exc
        try:
            from PIL import Image

            import numpy as np

            pil = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            arr = np.asarray(pil, dtype=np.uint8)
        finally:
            del shot
        return ScreenshotFrame(
            x=region.x,
            y=region.y,
            width=region.width,
            height=region.height,
            timestamp=timestamp or now_ts(),
            image=arr,
        )

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass

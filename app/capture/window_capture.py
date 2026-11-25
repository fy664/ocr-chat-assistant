"""A Qt window capture source and a window-relative crop for OCR."""
from __future__ import annotations

import ctypes
from ctypes import byref, create_unicode_buffer, wintypes
from dataclasses import dataclass
from functools import lru_cache
from hashlib import blake2b
import os

import numpy as np
from PySide6.QtCore import QObject, QRect, Slot
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QCapturableWindow, QMediaCaptureSession, QVideoSink, QWindowCapture

from app.capture.screen_capture import CaptureError
from app.models.schemas import ScreenRegion, ScreenshotFrame
from app.utils.time import now_ts


@lru_cache(maxsize=1)
def _win32():
    user32 = ctypes.WinDLL("user32")
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    signatures = {
        "EnumWindows": ((callback, wintypes.LPARAM), wintypes.BOOL),
        "GetWindowRect": ((wintypes.HWND, ctypes.POINTER(wintypes.RECT)), wintypes.BOOL),
        "GetWindowTextLengthW": ((wintypes.HWND,), wintypes.INT),
        "GetWindowTextW": ((wintypes.HWND, wintypes.LPWSTR, wintypes.INT), wintypes.INT),
        "GetWindowThreadProcessId": ((wintypes.HWND, ctypes.POINTER(wintypes.DWORD)), wintypes.DWORD),
        "IsIconic": ((wintypes.HWND,), wintypes.BOOL),
        "IsWindowVisible": ((wintypes.HWND,), wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(user32, name)
        function.argtypes = args
        function.restype = result
    return user32, callback


def _title(user32, hwnd):
    buffer = create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value.strip()


def _pid(user32, hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    return pid.value


@dataclass(frozen=True)
class WindowChoice:
    window: QCapturableWindow
    title: str
    # Qt captures the selected window object directly. An unambiguous native
    # match lets us also detect minimization and size changes before a new frame.
    handle: int | None = None
    pid: int | None = None

    def native_size(self) -> tuple[int, int] | None:
        if self.handle is None:
            return None
        user32, _ = _win32()
        rect = wintypes.RECT()
        if user32.GetWindowRect(self.handle, byref(rect)):
            return rect.right - rect.left, rect.bottom - rect.top
        return None

    @property
    def closed(self) -> bool:
        return not self.window.isValid()

    def problem(self) -> str:
        if self.closed:
            return "所选窗口已关闭或不可用，请重新选择窗口"
        if self.handle is not None:
            user32, _ = _win32()
            if _pid(user32, self.handle) != self.pid:
                return "所选窗口已关闭或不可用，请重新选择窗口"
            if user32.IsIconic(self.handle):
                return "所选窗口已最小化，请恢复窗口"
            if _title(user32, self.handle) != self.title:
                return "所选窗口标题已变化，请恢复原会话或重新选择"
        return ""


def window_choices(excluded_title: str) -> list[WindowChoice]:
    user32, enum_proc = _win32()
    matches: dict[str, list[tuple[int, int]]] = {}

    @enum_proc
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title = _title(user32, hwnd)
            if title:
                matches.setdefault(title, []).append((hwnd, _pid(user32, hwnd)))
        return True

    user32.EnumWindows(collect, 0)
    choices = []
    for window in QWindowCapture.capturableWindows():
        title = window.description().strip()
        if not title or title == excluded_title or not window.isValid():
            continue
        candidates = matches.get(title, [])
        if candidates and all(pid == os.getpid() for _, pid in candidates):
            continue
        handle, pid = candidates[0] if len(candidates) == 1 else (None, None)
        choices.append(WindowChoice(window, title, handle, pid))
    return sorted(choices, key=lambda choice: choice.title.casefold())


def _crop(image: QImage, region: ScreenRegion) -> np.ndarray:
    image = image.copy(QRect(region.x, region.y, region.width, region.height))
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    rows = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
    return rows[:, :image.width() * 3].reshape(image.height(), image.width(), 3).copy(order="C")


def _fingerprint(image: QImage, region: ScreenRegion) -> bytes:
    return blake2b(_crop(image, region), digest_size=16).digest()


def _fits(region: ScreenRegion, width: int, height: int) -> bool:
    return (0 <= region.x <= width - region.width
            and 0 <= region.y <= height - region.height)


@dataclass(frozen=True)
class WindowSelection:
    target: WindowChoice
    region: ScreenRegion
    frame_size: tuple[int, int]
    native_size: tuple[int, int] | None
    marker: ScreenRegion | None = None
    marker_hash: bytes | None = None

    @classmethod
    def from_preview(cls, target, image, region, marker=None):
        size = image.width(), image.height()
        if image.isNull() or not _fits(region, *size) or (marker and not _fits(marker, *size)):
            raise CaptureError("选区已失效，请刷新预览并重新框选")
        return cls(target, region, size, target.native_size(), marker,
                   _fingerprint(image, marker) if marker is not None else None)


class WindowFeed(QObject):
    """Read only the newest video frame, converting it to an image on demand."""

    def __init__(self, target: WindowChoice, parent=None):
        super().__init__(parent)
        self.target = target
        self._capture = QWindowCapture(self)
        self._session = QMediaCaptureSession(self)
        self._sink = QVideoSink(self)
        self._session.setWindowCapture(self._capture)
        self._session.setVideoSink(self._sink)
        self._capture.setWindow(target.window)
        self._capture.errorOccurred.connect(self._on_error)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._sequence = 0
        self._last_converted = -1
        self._invalidate_at = 0
        self._image = QImage()
        self._closed = False
        self.error = ""

    def start(self) -> None:
        self._capture.start()

    def snapshot(self) -> tuple[QImage, str]:
        if self._closed:
            return QImage(), "窗口采集已结束"
        problem = self.target.problem() or self.error
        if problem:
            self._invalidate_at = self._sequence
            self._image = QImage()
            return QImage(), problem
        if self._sequence <= self._invalidate_at:
            return QImage(), "正在等待所选窗口的画面"
        if self._last_converted != self._sequence:
            self._image = self._sink.videoFrame().toImage()
            self._last_converted = self._sequence
        if self._image.isNull():
            return QImage(), "正在等待所选窗口的画面"
        return self._image, ""

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._capture.stop()
        self._session.setVideoSink(None)
        self._image = QImage()
        self.deleteLater()

    @Slot()
    def _on_frame(self) -> None:
        self._sequence += 1

    def _on_error(self, _code, text: str) -> None:
        self.error = f"窗口采集已停止：{text or '无法取得画面'}"


class WindowRegionCapture:
    """A window source that fulfills the same sampling contract as ScreenCapture."""

    def __init__(self, selection: WindowSelection, feed: WindowFeed | None = None):
        self.selection = selection
        self._feed = feed or WindowFeed(selection.target)
        self._preview_key: int | None = None

    @property
    def ended(self) -> bool:
        return self.selection.target.closed or bool(self._feed.error)

    def start(self) -> None:
        self._feed.start()

    def _validated_image(self, region: ScreenRegion) -> QImage:
        image, reason = self._feed.snapshot()
        if reason:
            raise CaptureError(reason)
        selection = self.selection
        size = image.width(), image.height()
        if (size != selection.frame_size or not _fits(region, *size)
                or selection.target.native_size() != selection.native_size):
            raise CaptureError("窗口尺寸或缩放已变化，请结束采集并重新框选")
        if selection.marker is not None and _fingerprint(image, selection.marker) != selection.marker_hash:
            raise CaptureError("会话标题区域已变化，请返回原会话或重新选择")
        return image

    def check(self, region: ScreenRegion) -> tuple[bool, str]:
        try:
            self._validated_image(region)
        except CaptureError as exc:
            self._preview_key = None
            return False, str(exc)
        return True, ""

    def preview_frame(self, region: ScreenRegion) -> QImage | None:
        """Return a new preview frame without copying pixels into an OCR array."""
        try:
            image = self._validated_image(region)
        except CaptureError:
            self._preview_key = None
            raise
        key = image.cacheKey()
        if key == self._preview_key:
            return None
        self._preview_key = key
        return image.copy(QRect(region.x, region.y, region.width, region.height))

    def capture(self, region: ScreenRegion, timestamp: float | None = None) -> ScreenshotFrame:
        image = _crop(self._validated_image(region), region)
        return ScreenshotFrame(x=region.x, y=region.y, width=region.width, height=region.height,
                               timestamp=timestamp or now_ts(), image=image)

    def close(self) -> None:
        self._feed.close()

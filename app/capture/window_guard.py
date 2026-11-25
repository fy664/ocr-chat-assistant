"""Foreground-window guard for continuous capture.

While collecting a transcript the user is expected to switch to the chat
application and scroll it. Two things can invalidate the capture:

1. the selected region is no longer fully on screen (window moved, resolution
   changed, another screen took over);
2. the foreground window does not cover the selected region (the user switched
   to another application, or a dialog popped up on top).

Both cases should pause collection rather than record garbage. The check is
implemented with a tiny ctypes probe, and the probe function is injectable so
the behaviour can be unit-tested without a desktop.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger("ocr_chat.window_guard")

#: The foreground window may be a few pixels narrower than the region (rounded
#: borders, taskbar gaps); treat that as covered.
DEFAULT_TOLERANCE = 8


def _probe_foreground_rect():
    """(left, top, right, bottom) of the foreground window's client area."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    point = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    left, top = point.x, point.y
    return (
        left,
        top,
        left + (rect.right - rect.left),
        top + (rect.bottom - rect.top),
    )


def _probe_foreground_handle():
    """(hwnd, pid) of the foreground window, ``None`` on other platforms."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(hwnd), int(pid.value)


def _probe_screen_bounds():
    """(left, top, right, bottom) of the whole virtual desktop."""
    if sys.platform != "win32":
        return None
    import ctypes

    user32 = ctypes.windll.user32
    left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
    width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    height = user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN
    if width <= 0 or height <= 0:
        return None
    return (left, top, left + width, top + height)


class ForegroundGuard:
    """Decides whether the region is still the visible chat window."""

    def __init__(
        self,
        *,
        probe=None,
        bounds_probe=None,
        handle_probe=None,
        own_pid=None,
        tolerance=DEFAULT_TOLERANCE,
    ):
        self._probe = probe or _probe_foreground_rect
        self._bounds_probe = bounds_probe or _probe_screen_bounds
        self._handle_probe = handle_probe or _probe_foreground_handle
        self._own_pid = own_pid
        self._tolerance = int(tolerance)

    # ---- bounds -----------------------------------------------------------

    def bounds_problem(self, region) -> str:
        """``""`` when the region is fully inside the virtual desktop.

        Separated from :meth:`check` because the *focus* question ("is the
        foreground window the chat?") is meaningless when the app grabs one
        extra frame after the user clicked a button in our own window: at that
        moment our window is foreground by definition. Whether the pixels are
        even on screen, on the other hand, is always worth checking.
        """
        if region is None:
            return "还没有框选区域"
        bounds = self._safe(self._bounds_probe)
        if bounds is None:
            return ""
        sx0, sy0, sx1, sy1 = bounds
        if not (
            region.x >= sx0 - self._tolerance
            and region.y >= sy0 - self._tolerance
            and region.x + region.width <= sx1 + self._tolerance
            and region.y + region.height <= sy1 + self._tolerance
        ):
            return "选区不在屏幕范围内（窗口可能被移动或分辨率变了）"
        return ""

    # ---- focus ------------------------------------------------------------

    def _own_window_in_front(self, rect, region) -> bool:
        """True when the foreground window belongs to us and misses the region.

        Clicking 结束采集 in our own window necessarily makes *us* the
        foreground window, so the plain "foreground must cover the region"
        rule would refuse every final frame. Process identity settles that:
        our own window is foreground and does not overlap the region, so the
        pixels in the region are unchanged from the last accepted frame.
        """
        handle = self._safe(self._handle_probe)
        if handle is None:
            return False
        _hwnd, pid = handle
        if self._own_pid is None:
            try:
                import os

                self._own_pid = os.getpid()
            except Exception:  # pragma: no cover
                return False
        if pid != self._own_pid:
            return False
        return not _overlaps(*rect, region)

    def check(self, region) -> tuple[bool, str]:
        """``(ok, reason)`` - reason is empty when ok, Chinese otherwise."""
        if region is None:
            return False, "还没有框选区域"

        problem = self.bounds_problem(region)
        if problem:
            return False, problem

        rect = self._safe(self._probe)
        if rect is None:
            # Unknown environment (other OS, no window): never block the user.
            return True, ""
        left, top, right, bottom = rect
        if not (
            left <= region.x + self._tolerance
            and top <= region.y + self._tolerance
            and right >= region.x + region.width - self._tolerance
            and bottom >= region.y + region.height - self._tolerance
        ):
            if self._own_window_in_front(rect, region):
                return True, ""
            return False, "前台窗口没有覆盖选区（可能切换了聊天窗口）"
        return True, ""

    @staticmethod
    def _safe(probe):
        try:
            return probe()
        except Exception as exc:  # pragma: no cover - platform dependent
            logger.debug("window probe failed: %s", exc)
            return None


def _overlaps(left: int, top: int, right: int, bottom: int, region) -> bool:
    """True when the rect and the region share a meaningful area."""
    width = min(right, region.x + region.width) - max(left, region.x)
    height = min(bottom, region.y + region.height) - max(top, region.y)
    # A few shared pixels are window borders/shadow, not real occlusion.
    return width > 4 and height > 4

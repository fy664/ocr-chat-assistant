"""Small time helpers."""
from __future__ import annotations

import time


def now_ts() -> float:
    return time.time()


def format_clock(ts: float | None) -> str:
    if not ts:
        return "--:--:--"
    return time.strftime("%H:%M:%S", time.localtime(ts))


def format_elapsed(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.1f} s"

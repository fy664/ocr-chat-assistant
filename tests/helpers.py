"""Test helpers: stub OCR engine, wait helpers, mock LLM factory helpers."""
from __future__ import annotations

import time

from app.models.schemas import OCRLine, OCRResult, ScreenshotFrame
from app.ocr.normalize import normalize_text
from app.utils.time import now_ts


class StubOCREngine:
    """Programmable OCR engine: pops one text per recognize() call."""

    def __init__(self, texts=None, fail: bool = False):
        self.texts = list(texts or [])
        self.fail = fail
        self.calls = 0

    def recognize(self, image) -> OCRResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("stub OCR 故障（测试用）")
        text = self.texts.pop(0) if self.texts else ""
        ts = now_ts()
        lines: list[OCRLine] = []
        y = 10.0
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lines.append(
                OCRLine(
                    text=line,
                    confidence=0.9,
                    box=[[10.0, y], [300.0, y], [300.0, y + 18.0], [10.0, y + 18.0]],
                )
            )
            y += 22.0
        return OCRResult(
            raw_text=text,
            normalized_text=normalize_text(text),
            lines=lines,
            confidence=0.9,
            boxes=[ln.box for ln in lines],
            timestamp=ts,
        )


def make_frame(x: int = 0, y: int = 0, width: int = 400, height: int = 300) -> ScreenshotFrame:
    return ScreenshotFrame(x=x, y=y, width=width, height=height, timestamp=now_ts(), image=None)


def wait_until(qapp, predicate, timeout_ms: int = 5000, interval_ms: int = 10) -> bool:
    """Pump the Qt event loop until the predicate is true or timeout."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(interval_ms / 1000.0)
    qapp.processEvents()
    return predicate()

"""Qt worker threads. Heavy work (PaddleOCR, HTTP) never runs on the GUI
thread. Workers talk to the UI exclusively through Qt signals.

OCR worker implements the latest-only principle: at most the frame
currently being processed plus one pending slot holding the newest frame -
no unbounded queue.
"""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QThread, Signal

from app.models.schemas import OCRResult

logger = logging.getLogger("ocr_chat.workers")


class OCRWorkerThread(QThread):
    engine_ready = Signal()
    engine_failed = Signal(str)
    ocr_started = Signal(float)          # frame timestamp
    ocr_completed = Signal(object)       # OCRResult
    ocr_failed = Signal(str, float)      # message, frame timestamp

    def __init__(self, engine_factory, parent=None) -> None:
        super().__init__(parent)
        self._engine_factory = engine_factory
        self.engine = None  # created inside run() (Paddle must stay on this thread)
        self._lock = threading.Lock()
        self._pending_frame = None
        self._stopped = threading.Event()

    def submit(self, frame) -> None:
        """latest-only: replaces any frame waiting to be processed."""
        with self._lock:
            self._pending_frame = frame

    def stop(self) -> None:
        self._stopped.set()

    def _take_pending(self):
        with self._lock:
            frame, self._pending_frame = self._pending_frame, None
        return frame

    def run(self) -> None:
        try:
            engine = self._engine_factory()
            self.engine = engine
        except Exception as exc:
            logger.exception("OCR engine init failed")
            self.engine_failed.emit(f"OCR 引擎初始化失败：{exc}")
            return
        self.engine_ready.emit()
        while not self._stopped.is_set():
            frame = self._take_pending()
            if frame is None:
                self.msleep(20)
                continue
            self.ocr_started.emit(frame.timestamp)
            try:
                result: OCRResult = engine.recognize(frame.image)
                self.ocr_completed.emit(result)
            except Exception as exc:
                logger.warning("OCR failed on frame %s: %s", frame.timestamp, exc)
                self.ocr_failed.emit(f"OCR 识别失败：{exc}", frame.timestamp)


class LLMWorkerThread(QThread):
    """Executes at most one analysis request at a time (max_active_analysis=1
    is enforced by the scheduler; this worker additionally keeps only the
    newest submitted request)."""

    llm_completed = Signal(int, object)  # generation, AnalysisResult
    llm_failed = Signal(int, str)        # generation, friendly message
    llm_latency = Signal(int, float)     # generation, seconds

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending = None  # (generation, system_prompt, user_prompt, client)
        self._stopped = threading.Event()

    def submit(self, generation: int, system_prompt: str, user_prompt: str, client) -> None:
        with self._lock:
            self._pending = (generation, system_prompt, user_prompt, client)

    def stop(self) -> None:
        self._stopped.set()

    def _take_pending(self):
        with self._lock:
            pending, self._pending = self._pending, None
        return pending

    def run(self) -> None:
        while not self._stopped.is_set():
            pending = self._take_pending()
            if pending is None:
                self.msleep(20)
                continue
            generation, system_prompt, user_prompt, client = pending
            start = time.monotonic()
            try:
                result = client.analyze(system_prompt, user_prompt)
                self.llm_completed.emit(generation, result)
                self.llm_latency.emit(generation, time.monotonic() - start)
            except Exception as exc:
                logger.warning("LLM request failed (gen %s): %s", generation, exc)
                self.llm_failed.emit(generation, str(exc))
                self.llm_latency.emit(generation, time.monotonic() - start)

"""Qt worker threads. Heavy work (PaddleOCR, HTTP) never runs on the GUI
thread. Workers talk to the UI exclusively through Qt signals.

The OCR worker supports two submission modes:

* ``submit(frame)`` - latest-only. At most the frame being processed plus one
  pending slot holding the newest frame. This is the on-demand single-shot
  path: a newer screenshot simply replaces the older one.
* ``submit_sequenced(frame)`` - an ordered, bounded FIFO. Continuous scrolling
  capture must not lose frames silently: each frame gets a sequence number,
  results come back with the same number, and when the queue is full the new
  frame is rejected (``None`` + ``queue_full``) so the controller can tell the
  user to slow down and later check for a breakpoint.

Both modes can be used at the same time; the single-shot slot is drained first.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

from PySide6.QtCore import QThread, Signal

from app.analysis.chat_layout import recognize_chat_layout
from app.llm.provider import analyze_with_client
from app.llm.vision import encode_image_data_url
from app.models.schemas import OCRResult

logger = logging.getLogger("ocr_chat.workers")

#: Hard ceiling for the sequencer queue, independent of user settings.
MAX_QUEUE_HARD_LIMIT = 32


class OCRWorkerThread(QThread):
    engine_ready = Signal()
    engine_failed = Signal(str)
    ocr_started = Signal(float)          # frame timestamp
    ocr_completed = Signal(object)       # OCRResult (latest-only mode)
    ocr_failed = Signal(str, float)      # message, frame timestamp
    # Sequenced mode: the sequence number lets the controller pair a result
    # with the exact frame (and therefore with its scroll direction).
    ocr_sequenced = Signal(int, object)          # seq, OCRResult
    ocr_sequenced_failed = Signal(int, str, float)  # seq, message, timestamp
    queue_full = Signal(int)             # total dropped frames so far

    def __init__(self, engine_factory, parent=None, *, chat_layout: bool = False) -> None:
        super().__init__(parent)
        self._engine_factory = engine_factory
        self._chat_layout = chat_layout
        self.engine = None  # created inside run() (Paddle must stay on this thread)
        self._lock = threading.Lock()
        self._pending_frame = None
        self._queue: deque[tuple[int, object]] = deque()
        self._max_queue = 6
        self._seq = 0
        self._dropped = 0
        self._processing = False
        self._stopped = threading.Event()

    # ---- single-shot (latest-only) ---------------------------------------

    def submit(self, frame) -> None:
        """latest-only: replaces any frame waiting to be processed."""
        with self._lock:
            self._pending_frame = frame

    # ---- continuous capture (ordered, bounded) ----------------------------

    def set_max_queue(self, size: int) -> None:
        """Upper bound for frames waiting behind the one being processed."""
        with self._lock:
            self._max_queue = max(1, min(int(size), MAX_QUEUE_HARD_LIMIT))

    def submit_sequenced(self, frame) -> int | None:
        """Enqueue a frame for OCR; returns its sequence number.

        Returns ``None`` when the queue is already at its limit. The caller is
        expected to warn the user (scrolling faster than OCR can keep up) and
        to treat the gap as a possible breakpoint. Keeping the *older* frames
        preserves contiguous coverage; the final frame taken when the user
        stops collection covers the newest screen.
        """
        with self._lock:
            if len(self._queue) >= self._max_queue:
                self._dropped += 1
                dropped = self._dropped
            else:
                self._seq += 1
                seq = self._seq
                self._queue.append((seq, frame))
                dropped = -1
        if dropped >= 0:
            logger.warning("OCR queue full (%d), frame dropped", self._max_queue)
            self.queue_full.emit(dropped)
            return None
        return seq

    @property
    def pending_count(self) -> int:
        """Frames still waiting (includes the one currently being recognised)."""
        with self._lock:
            return len(self._queue) + (1 if self._processing else 0)

    @property
    def processing(self) -> bool:
        with self._lock:
            return self._processing

    @property
    def is_idle(self) -> bool:
        return self.pending_count == 0

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped

    def clear_queue(self) -> int:
        """Drop everything that is still waiting; returns how many frames went."""
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
        return count

    # ---- lifecycle --------------------------------------------------------

    def stop(self) -> None:
        self._stopped.set()

    def _take_pending(self):
        """Next item to process: ``(frame, seq)`` with seq None for single-shot.

        ``_processing`` is flipped **inside** the same lock as the pop. Doing it
        afterwards in :meth:`run` left a window where the queue was empty and the
        flag was still False, so ``is_idle`` lied and a "wait for OCR to drain"
        loop could finish before the frame it had just handed over was
        recognised.
        """
        with self._lock:
            if self._pending_frame is not None:
                frame, self._pending_frame = self._pending_frame, None
                self._processing = True
                return frame, None
            if self._queue:
                seq, frame = self._queue.popleft()
                self._processing = True
                return frame, seq
            return None, None

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
            frame, seq = self._take_pending()
            if frame is None:
                self.msleep(20)
                continue
            st = time.monotonic()
            self.ocr_started.emit(frame.timestamp)
            try:
                result: OCRResult = engine.recognize(frame.image)
                if self._chat_layout:
                    try:
                        result = recognize_chat_layout(result, frame.image)
                    except (ValueError, TypeError, RuntimeError):
                        logger.exception("Could not classify the chat layout; returning OCR text")
                if seq is None:
                    self.ocr_completed.emit(result)
                else:
                    self.ocr_sequenced.emit(seq, result)
            except Exception as exc:
                logger.warning("OCR failed on frame %s: %s", frame.timestamp, exc)
                if seq is None:
                    self.ocr_failed.emit(f"OCR 识别失败：{exc}", frame.timestamp)
                else:
                    self.ocr_sequenced_failed.emit(seq, f"OCR 识别失败：{exc}", frame.timestamp)
            finally:
                with self._lock:
                    self._processing = False
                cost = time.monotonic() - st
                if cost > 1.0:
                    logger.info("OCR took %.2fs on one frame", cost)


class LLMWorkerThread(QThread):
    """Executes at most one analysis request at a time (max_active_analysis=1
    is enforced by the scheduler; this worker additionally keeps only the
    newest submitted request)."""

    llm_completed = Signal(int, object)  # generation, AnalysisResult
    llm_failed = Signal(int, str)        # generation, friendly message
    llm_latency = Signal(int, float)     # generation, seconds
    llm_reasoning = Signal(int, str)     # generation, reasoning delta
    llm_status = Signal(int, str)        # generation, phase ("requesting"/"first_token"/...)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending = None  # (generation, system_prompt, user_prompt, client, images, vision_opts, thinking)
        self._stopped = threading.Event()

    def submit(
        self,
        generation: int,
        system_prompt: str,
        user_prompt: str,
        client,
        images=(),
        vision_options=(1024, 80),
        thinking_enabled: bool = True,
    ) -> None:
        with self._lock:
            self._pending = (
                generation,
                system_prompt,
                user_prompt,
                client,
                tuple(images or ()),
                tuple(vision_options),
                bool(thinking_enabled),
            )

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
            (
                generation,
                system_prompt,
                user_prompt,
                client,
                images,
                vision_options,
                thinking_enabled,
            ) = pending
            start = time.monotonic()
            try:
                image_urls: list[str] = []
                if images:
                    self.llm_status.emit(generation, "encoding")
                    max_side, quality = vision_options
                    for frame_image in images:
                        url = encode_image_data_url(frame_image, max_side, quality)
                        if url:
                            image_urls.append(url)

                def on_reasoning(delta: str) -> None:
                    self.llm_reasoning.emit(generation, delta)

                def on_status(status: str) -> None:
                    self.llm_status.emit(generation, status)

                result = analyze_with_client(
                    client,
                    system_prompt,
                    user_prompt,
                    images=image_urls or None,
                    on_reasoning=on_reasoning if thinking_enabled else None,
                    on_status=on_status,
                )
                if image_urls:
                    result.vision_used = True
                self.llm_completed.emit(generation, result)
                self.llm_latency.emit(generation, time.monotonic() - start)
            except Exception as exc:
                logger.warning("LLM request failed (gen %s): %s", generation, exc)
                self.llm_failed.emit(generation, str(exc))
                self.llm_latency.emit(generation, time.monotonic() - start)

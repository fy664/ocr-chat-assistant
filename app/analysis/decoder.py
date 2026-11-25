"""On-demand conversation decoder.

No screen monitoring, no debounce, no repeated LLM calls: the user explicitly
captures one or more screens, optionally pastes a long conversation, then asks
for a single decode. This is the v2 product path.

v2.1 adds continuous *scrolling* collection: the user selects the chat region,
scrolls it themselves, and every sampled screen is OCR-ed locally and stitched
into one transcript. Model requests start on manual or opt-in automatic analysis.
"""
from __future__ import annotations

import logging
import time

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from app.agent.conversation import ConversationRequest
from app.agent.worker import ConversationWorker
from app.analysis.chat_layout import crop_chat_frame, labeled_lines, recognize_chat_layout
from app.analysis.capture_session import (
    STATE_COLLECTING,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_STOPPING,
    CaptureSession,
)
from app.analysis.stitch import TranscriptStitcher, page_lines_from_ocr
from app.analysis.workers import OCRWorkerThread
from app.capture.screen_capture import CaptureError, ScreenCapture
from app.capture.window_capture import WindowRegionCapture, WindowSelection
from app.llm.client import MockLLMClient
from app.llm.provider import (
    LLMNotConfiguredError,
    create_llm_client,
)
from app.llm.vision import encode_image_data_url
from app.models.schemas import ConversationInfo, ScreenshotFrame, ScreenRegion
from app.ocr.engine import build_engine
from app.utils.time import format_clock, now_ts

logger = logging.getLogger("ocr_chat.decoder")

STAGES = (
    ("capture", "读取画面"),
    ("text", "整理文本"),
    ("vision", "画面理解"),
    ("decode", "语义解读"),
)


class DecoderController(QObject):
    """Owns one lazy OCR worker and one decode request at a time."""

    state_changed = Signal(str)
    status_message = Signal(str)
    engine_status_changed = Signal(str)
    ocr_activity = Signal(bool)
    llm_activity = Signal(bool)
    busy_changed = Signal(bool)
    pipeline_log = Signal(str)
    stage_changed = Signal(str, str)
    frame_preview = Signal(object)
    images_changed = Signal(int)
    capture_completed = Signal(str)
    conversation_changed = Signal(object)
    capture_conversation_switched = Signal()
    analysis_started = Signal()
    thinking_started = Signal()
    thinking_delta = Signal(str)
    analysis_completed = Signal(object)
    analysis_failed = Signal(str)
    last_update = Signal(float)
    metrics_updated = Signal(dict)
    cleared = Signal()
    # Continuous scrolling collection
    collection_state_changed = Signal(str)   # 采集中 / 暂停 / 收尾 / 已采集
    collection_status = Signal(dict)         # counters for the status strip
    collection_hint = Signal(str)            # "队列已满，请放慢滚动" etc.
    collection_completed = Signal(dict)      # {text, lines, breakpoints, ...}

    def __init__(
        self,
        settings,
        *,
        mock_llm: bool = False,
        ocr_engine_factory=None,
        client_factory=None,
        capture_factory=None,
        session_factory=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._mock_llm = bool(mock_llm)
        self._ocr_factory = ocr_engine_factory
        self._client_factory = client_factory
        self._capture_factory = capture_factory
        self._session_factory = session_factory
        self._capture = None
        self._ocr_worker = None
        self._region: ScreenRegion | None = None
        self._window_selection: WindowSelection | None = None
        self._window_reader: WindowRegionCapture | None = None
        self._window_read_until = 0.0
        self._window_read_timer = QTimer(self)
        self._window_read_timer.setInterval(50)
        self._window_read_timer.timeout.connect(self._read_window_frame)
        self._images: list[str] = []
        self._conversation: ConversationInfo | None = None
        self._single_frame = None
        self._chat_bounds = None
        self._capture_token = 0
        self._decode_token = 0
        self._pending_capture_token = 0
        self._capturing = False
        self._busy = False
        self._state = "待机"
        self._last_text_chars = 0
        self._last_latency = 0.0
        self._started_at = 0.0
        self._worker = None
        self._closing = False
        # collection
        self._stitcher: TranscriptStitcher | None = None
        self._session: CaptureSession | None = None
        self._frame_dirs: dict[int, int] = {}
        self._pending_images: dict[int, object] = {}
        self._confirmed_image = None
        # Sequence numbers submitted but whose result has not been folded into
        # the stitcher yet. ``worker.is_idle`` only covers the worker thread; a
        # result can still be sitting in the main thread's event queue, and
        # finishing at that moment would throw that frame away.
        self._inflight: set[int] = set()
        self._submit_at: dict[int, float] = {}
        #: Wall-clock seconds per finished frame, used to size the drain budget
        #: and to tell the user how much longer收尾 will take.
        self._ocr_durations: list[float] = []
        self._last_drain_hint = 0.0
        self._collecting = False
        self._collection_stopping = False
        self._collection_started_at = 0.0
        self._collection_dropped = 0
        self._collection_frames = 0
        self._collection_state_label = ""
        self._last_frame = None
        self._last_frame_seq: int | None = None
        self._last_scroll_direction = 1
        self._last_recognized_seq: int | None = None
        self._drain_timer: QTimer | None = None
        self._drain_deadline = 0.0

    # ------------------------------------------------------------------ state
    @property
    def region(self) -> ScreenRegion | None:
        return self._region

    @property
    def images(self) -> list[str]:
        return list(self._images)

    @property
    def image_count(self) -> int:
        return len(self._images)

    @property
    def busy(self) -> bool:
        return self._busy or self._capturing

    def set_settings(self, settings) -> None:
        self._settings = settings
        if not settings.vision_enabled:
            self.clear_images(announce=False)
        while len(self._images) > settings.max_screenshots:
            self._images.pop(0)
        self.images_changed.emit(len(self._images))

    @property
    def window_selection(self) -> WindowSelection | None:
        return self._window_selection

    def set_region(self, region: ScreenRegion) -> None:
        self._region = region
        self._window_selection = None

    def set_window_selection(self, selection: WindowSelection) -> None:
        self._window_selection = selection
        self._region = selection.region

    def clear_images(self, *, announce: bool = True) -> None:
        self._images.clear()
        self.images_changed.emit(0)
        if announce:
            self._log("已清空附带画面")

    def clear(self) -> None:
        self._decode_token += 1
        if self._worker is not None:
            self._worker.requestInterruption()
        self._set_conversation(None)
        self._single_frame = None
        self._capture_token += 1
        self._pending_capture_token = -1
        self._abort_collection()
        self._close_window_reader()
        self._window_selection = None
        self._capturing = False
        self._busy = False
        self._images.clear()
        self._region = None
        self._last_text_chars = 0
        self._last_latency = 0.0
        self._set_busy(False)
        self.ocr_activity.emit(False)
        self.llm_activity.emit(False)
        self.images_changed.emit(0)
        self._reset_stages()
        self._set_state("待机")
        self._publish_metrics()
        self.cleared.emit()

    # ---------------------------------------------------------------- capture
    def capture(self, region: ScreenRegion | None = None) -> None:
        if self._closing:
            return
        if self.collecting:
            self._status("正在连续采集，先点「结束采集」再读取单张画面")
            return
        if self._capturing:
            self._status("正在读取上一张画面，请稍等")
            return
        if self._busy:
            self._status("正在解读，请等这次结果出来再读取画面")
            return
        if region is not None and region != self._region:
            self.set_region(region)
        if self._region is None:
            self._status("请先框选一个聊天区域")
            return
        if self._window_selection is not None:
            self._start_window_read(self._window_selection)
            return
        try:
            if self._capture is None:
                self._capture = (self._capture_factory or ScreenCapture)()
            frame = self._capture.capture(self._region)
        except (CaptureError, Exception) as exc:
            logger.warning("capture failed: %s", exc)
            self._status(f"截图失败：{exc}")
            self._set_state("错误")
            return
        self._handle_frame(frame)

    def _start_window_read(self, selection: WindowSelection) -> None:
        self._window_reader = WindowRegionCapture(selection)
        self._window_reader.start()
        self._window_read_until = time.monotonic() + 3.0
        self._set_busy(True)
        self._status("正在读取所选窗口的聊天区域…")
        self._window_read_timer.start()

    def _read_window_frame(self) -> None:
        reader = self._window_reader
        if reader is None:
            return
        try:
            frame = reader.capture(reader.selection.region)
        except CaptureError as exc:
            if time.monotonic() < self._window_read_until:
                return
            self._close_window_reader()
            self._set_busy(False)
            self._set_state("错误")
            self._status(f"无法读取所选窗口：{exc}")
            return
        self._close_window_reader()
        self._handle_frame(frame)

    def _close_window_reader(self) -> None:
        self._window_read_timer.stop()
        reader, self._window_reader = self._window_reader, None
        if reader is not None:
            reader.close()

    def capture_from_image(self, image) -> None:
        """Test / clipboard helper: decode an already captured RGB array."""
        if self._closing or self._busy or self.collecting or self._capturing:
            return
        if image is None:
            self._status("没有可读取的画面")
            return
        try:
            height, width = image.shape[:2]
        except Exception:
            self._status("画面格式不可用")
            return
        frame = ScreenshotFrame(
            x=0,
            y=0,
            width=int(width),
            height=int(height),
            timestamp=now_ts(),
            image=image,
        )
        self._handle_frame(frame)

    def _handle_frame(self, frame: ScreenshotFrame) -> None:
        self._capture_token += 1
        token = self._capture_token
        self._pending_capture_token = token
        self._capturing = True
        self._set_busy(True)
        self._set_state("读取中")
        self._stage("capture", "active")
        self._stage("text", "idle")
        self._stage("vision", "idle")
        self._stage("decode", "idle")
        self.ocr_activity.emit(True)
        self._log("读取画面 · 本次按需读取，不开启持续监控")

        self.frame_preview.emit(frame.image)

        self._single_frame = frame
        self._ensure_ocr()
        self._ocr_worker.submit(frame)
        self._status("正在本地识别文字；可同时把长聊天记录粘贴到左侧")

    def _ensure_ocr(self):
        if self._ocr_worker is not None:
            return self._ocr_worker
        factory = self._ocr_factory or build_engine
        worker = OCRWorkerThread(factory, chat_layout=True)
        worker.engine_ready.connect(self._on_engine_ready)
        worker.engine_failed.connect(self._on_engine_failed)
        worker.ocr_completed.connect(self._on_ocr_completed)
        worker.ocr_failed.connect(self._on_ocr_failed)
        worker.ocr_sequenced.connect(self._on_ocr_sequenced)
        worker.ocr_sequenced_failed.connect(self._on_ocr_sequenced_failed)
        worker.queue_full.connect(self._on_queue_full)
        self._ocr_worker = worker
        self.engine_status_changed.emit("正在加载 OCR 模型…")
        worker.start()
        return worker

    def _on_engine_ready(self) -> None:
        self.engine_status_changed.emit("OCR 模型就绪")
        self._log("OCR 模型就绪 · 只在读取画面时使用")

    def _on_engine_failed(self, message: str) -> None:
        worker, self._ocr_worker = self._ocr_worker, None
        if worker is not None:
            worker.wait(500)
            worker.deleteLater()
        self._capturing = False
        self._single_frame = None
        if self.collecting:
            self._abort_collection()
            self._set_busy(False)
            self.collection_hint.emit("OCR 引擎不可用，采集已停止")
        self._set_busy(False)
        self.ocr_activity.emit(False)
        self._stage("capture", "error")
        self._set_state("错误")
        self._status(message)
        self._log(message)

    def _on_ocr_completed(self, result) -> None:
        if self._pending_capture_token != self._capture_token:
            return
        if self._different_conversation(result.conversation):
            self.clear_images(announce=False)
            self.capture_conversation_switched.emit()
            self._set_conversation(None)
        self._observe_conversation(result.conversation)
        frame, self._single_frame = self._single_frame, None
        if frame is not None:
            self._attach_chat_image(frame.image, result.chat_bounds)
        line_text = "\n".join(line for line in labeled_lines(result.lines) if line.strip())
        text = (line_text or result.raw_text or result.normalized_text or "").strip()
        self._capturing = False
        self._set_busy(False)
        self.ocr_activity.emit(False)
        self._stage("capture", "done")
        self._stage("text", "done")
        self._log(
            f"识别完成 · {len(result.lines)} 行 · 置信度 {result.confidence:.0%} · "
            f"{len(text)} 字"
        )
        self._set_state("已读取")
        self._publish_metrics()
        self.capture_completed.emit(text)
        if not text:
            if self._images:
                self._status("未识别到文字，但画面已保留；可以直接解读表情包/图片")
            else:
                self._status("未识别到文字，请调整选区或直接粘贴聊天记录")
        else:
            self._status(f"已读取 {len(text)} 字；可继续追加，或点击「解读这段对话」")

    def _on_ocr_failed(self, message: str, _timestamp: float) -> None:
        if self._pending_capture_token != self._capture_token:
            return
        self._single_frame = None
        self._capturing = False
        self._set_busy(False)
        self.ocr_activity.emit(False)
        self._stage("capture", "error")
        self._set_state("错误")
        self._status(message)
        self._log(message)

    def _set_conversation(self, conversation: ConversationInfo | None) -> None:
        if self._conversation != conversation:
            self._conversation = conversation
            self.conversation_changed.emit(conversation)

    def _observe_conversation(self, observation: ConversationInfo | None) -> None:
        if observation is None:
            return
        previous = self._conversation
        if previous is None:
            self._set_conversation(observation)
            return
        adopt_kind = observation.kind != "unknown" and (
            previous.kind == "unknown" or (previous.tentative and not observation.tentative)
        )
        best = observation if adopt_kind else previous
        self._set_conversation(best.model_copy(update={
            "title": observation.title or previous.title,
            "sidebar_selected": observation.sidebar_selected or previous.sidebar_selected,
        }))

    def _different_conversation(self, observation: ConversationInfo | None) -> bool:
        if not (self._conversation and self._conversation.title and observation and observation.title):
            return False
        old = "".join(self._conversation.title.split()).casefold()
        new = "".join(observation.title.split()).casefold()
        return old != new

    def forget_conversation(self) -> None:
        self._set_conversation(None)

    def _attach_chat_image(self, image, bounds) -> None:
        if self._settings.vision_enabled and image is not None:
            url = encode_image_data_url(
                crop_chat_frame(image, bounds),
                max_side=self._settings.vision_max_side,
                quality=self._settings.vision_quality,
            )
            if url:
                self._add_image(url)

    def _add_image(self, url: str) -> None:
        if not url or url in self._images:
            return
        limit = max(1, int(self._settings.max_screenshots))
        self._images.append(url)
        while len(self._images) > limit:
            self._images.pop(0)
        self.images_changed.emit(len(self._images))
        self._log(f"画面已附带 · 共 {len(self._images)} 张（表情包/贴纸可被视觉理解）")

    # ------------------------------------------------- continuous collection
    @property
    def collecting(self) -> bool:
        return self._collecting or self._collection_stopping

    @property
    def stitcher(self) -> TranscriptStitcher | None:
        return self._stitcher

    def start_collection(self, region: ScreenRegion | None = None) -> bool:
        """Start sampling the selected region until ``stop_collection()``.

        Returns False (with a status message) when another task is running.
        """
        if self._closing:
            return False
        if self.collecting:
            self._status("正在采集，先点「结束采集」")
            return False
        if self._capturing or self._busy:
            self._status("正在读取画面或解读，请稍后再开始采集")
            return False
        if region is not None and region != self._region:
            self.set_region(region)
        if self._region is None:
            self._status("请先框选聊天区域，再开始采集")
            return False

        worker = self._ensure_ocr()
        if worker is None:  # engine failed to start; the error is already reported
            return False
        worker.set_max_queue(int(self._settings.scroll_max_queue))

        self._stitcher = TranscriptStitcher(
            match_threshold=float(self._settings.scroll_match_threshold),
            min_overlap_lines=int(self._settings.scroll_min_overlap_lines),
        )
        self._frame_dirs.clear()
        self._pending_images.clear()
        self._confirmed_image = None
        self._inflight.clear()
        self._submit_at.clear()
        self._ocr_durations.clear()
        self._collection_dropped = 0
        self._collection_frames = 0
        self._last_frame = None
        self._last_frame_seq = None
        self._last_scroll_direction = 1
        self._last_recognized_seq = None
        self._collection_started_at = time.monotonic()
        self._chat_bounds = None
        self._set_conversation(None)
        self.clear_images(announce=False)

        if self._session_factory is not None:
            session = self._session_factory(self._region)
        else:
            source = None
            if self._window_selection is not None:
                source = WindowRegionCapture(self._window_selection)
                source.start()
            session = CaptureSession(
                self._region,
                interval_ms=int(self._settings.scroll_capture_interval_ms),
                preview_interval_ms=33 if source is not None else 83,
                capture=source,
                guard=source,
            )
        session.frame_ready.connect(self._on_collection_frame)
        session.paused.connect(self._on_collection_paused)
        session.resumed.connect(self._on_collection_resumed)
        session.state_changed.connect(self._on_collection_state)
        session.error.connect(self._on_collection_error)
        if isinstance(session, CaptureSession):
            session.source_ended.connect(self._on_collection_source_ended)
            session.preview_ready.connect(self.frame_preview)
        session.status_changed.connect(self._on_collection_status)
        self._session = session
        self.frame_preview.emit(None)

        self._collecting = True
        self._collection_stopping = False
        self._collection_state_label = "等待滚动"
        self._set_busy(True)
        self._set_state("采集中")
        self._stage("capture", "active")
        self._stage("text", "active")
        self._log("开始连续采集 · 请在聊天窗口里缓慢上下滚动，程序只在本地识别")
        self._status("正在采集：滚动聊天窗口，文字会自动拼起来；结束后可编辑和导出")
        session.start()
        self._emit_collection_status()
        return True

    def stop_collection(self) -> None:
        """Stop sampling, take one final frame, then wait for OCR to drain."""
        if not self._collecting:
            return
        self._collecting = False
        self._collection_stopping = True
        if self._session is not None:
            self._session.stop()
        self._set_state("收尾")
        self._status("已停止滚动采样，正在处理最后几帧画面…")
        self._log("结束采样 · 等待已入队的画面识别完成")

        if self._session is not None:
            final = self._session.capture_now()
            if final is not None:
                previous = self._last_frame
                self._last_frame = final
                # Compare only against a frame this session has successfully
                # stitched. Dropped, empty or still pending frames need OCR.
                already_recognized = (
                    self._last_frame_seq is not None
                    and self._last_frame_seq == self._last_recognized_seq
                    and previous is not None
                    and final.image is not None
                    and np.array_equal(previous.image, final.image)
                )
                if not already_recognized and self._submit_final_frame(final) is None:
                    self.collection_hint.emit("最后一帧未能入队，结果可能缺少最后看见的内容")
            session, self._session = self._session, None
            session.close()
        self._start_drain_timer()
        self._emit_collection_status()

    def _submit_final_frame(self, frame) -> int | None:
        worker = self._ocr_worker
        if worker is None:
            return None
        seq = worker.submit_sequenced(frame)
        self._last_frame_seq = seq
        if seq is not None:
            self._pending_images[seq] = frame.image
            direction = 0
            if isinstance(self._session, CaptureSession):
                direction = self._session.final_frame_direction(frame)
            self._frame_dirs[seq] = direction or self._last_scroll_direction
            self._submit_at[seq] = time.monotonic()
            self._inflight.add(seq)
            self._collection_frames += 1
        return seq

    def _start_drain_timer(self) -> None:
        if self._drain_timer is None:
            self._drain_timer = QTimer(self)
            self._drain_timer.setInterval(150)
            self._drain_timer.timeout.connect(self._check_drained)
        # A fixed 15 s cap is too short for a real telegram window: one 750x485
        # frame takes seconds on a laptop CPU, so a full queue needs minutes.
        # Scale the cap by the measured per-frame cost, and keep a floor.
        remaining = len(self._inflight)
        worker = self._ocr_worker
        if worker is not None:
            remaining = max(remaining, worker.pending_count)
        unit_s = self._ocr_unit_seconds()
        self._drain_deadline = time.monotonic() + max(15.0, remaining * unit_s * 1.5 + 5.0)
        self._last_drain_hint = 0.0
        self._drain_timer.start()

    def _ocr_unit_seconds(self) -> float:
        """Average wall time of one OCR frame in this session (8 s by default)."""
        samples = [d for d in self._ocr_durations if d > 0]
        if not samples:
            return 8.0
        samples.sort()
        return samples[len(samples) // 2]

    def _check_drained(self) -> None:
        if not self._collection_stopping:
            return
        worker = self._ocr_worker
        idle = worker is None or worker.is_idle
        # ``is_idle`` alone is not enough: the result of a frame the worker has
        # already recognised may still be queued in this thread's event loop.
        # Finishing now would detach the stitcher and silently drop it.
        if idle and not self._inflight:
            self._finish_collection()
            return
        now = time.monotonic()
        if now - self._last_drain_hint >= 1.0 and self._inflight:
            # Tell the user *why* the app is still busy, with a live count.
            self._last_drain_hint = now
            self.collection_hint.emit(
                f"收尾中：还有 {len(self._inflight)} 帧在识别，完成后自动出结果"
            )
        if now > self._drain_deadline:
            rest = len(self._inflight)
            self._log(
                f"等待 OCR 收尾超时，先输出已有结果（仍有 {rest} 帧未回传）"
            )
            self.collection_hint.emit(
                f"收尾已超时，仍有 {rest} 帧没识别完：先输出已有内容，缺的部分会标断点"
            )
            self._finish_collection()

    def _finish_collection(self) -> None:
        if self._drain_timer is not None:
            self._drain_timer.stop()
        stitcher, self._stitcher = self._stitcher, None
        text = stitcher.text(include_speakers=True) if stitcher is not None else ""
        stats = dict(stitcher.stats) if stitcher is not None else {}
        breakpoints = [
            {"reason": b.reason, "page": b.page, "direction": b.direction}
            for b in (stitcher.breakpoints if stitcher is not None else [])
        ]
        elapsed = time.monotonic() - self._collection_started_at

        # Attach the latest OCR-confirmed image from this conversation.
        if self._confirmed_image is not None:
            image, bounds = self._confirmed_image
            self._attach_chat_image(image, bounds)

        session, self._session = self._session, None
        if session is not None:
            session.close()
        self._last_frame = None
        self._frame_dirs.clear()
        self._pending_images.clear()
        self._confirmed_image = None
        self._inflight.clear()
        self._submit_at.clear()
        self._collection_stopping = False
        self._set_busy(False)
        self._set_state("已采集")
        self._stage("capture", "done")
        self._stage("text", "done")

        payload = {
            "text": text,
            "lines": stats.get("lines", 0),
            "pages": stats.get("pages", 0),
            "breakpoints": breakpoints,
            "dropped": self._collection_dropped,
            "frames": self._collection_frames,
            "elapsed_ms": round(elapsed * 1000.0, 1),
            "images": len(self._images),
        }
        self._log(
            f"采集完成 · {payload['pages']} 屏 · {payload['lines']} 行 · "
            f"{len(breakpoints)} 个断点 · 丢帧 {payload['dropped']}"
        )
        if breakpoints:
            self._status(
                f"已拼接 {payload['lines']} 行，但有 {len(breakpoints)} 处没有可靠重叠；"
                "可向上滚动到断点位置再补采一次"
            )
        elif payload["dropped"]:
            self._status(
                f"已拼接 {payload['lines']} 行（有 {payload['dropped']} 帧因滚动过快被丢弃，"
                "建议下次放慢滚动）"
            )
        else:
            self._status(f"已拼接 {payload['lines']} 行；可以直接编辑、复制、导出或解读这段对话")
        self._emit_collection_status()
        self.collection_completed.emit(payload)

    # ---- collection signal handlers ---------------------------------------

    def _on_collection_frame(self, frame, direction: int) -> None:
        self._last_scroll_direction = direction or self._last_scroll_direction
        self._last_frame = frame
        self._collection_frames += 1
        worker = self._ocr_worker
        if worker is None:
            return
        seq = worker.submit_sequenced(frame)
        self._last_frame_seq = seq
        if seq is None:
            self._collection_dropped += 1
            self.collection_hint.emit("滚动太快，画面队列已满：请放慢滚动速度（结果里会出现断点）")
        else:
            self._pending_images[seq] = frame.image
            self._frame_dirs[seq] = self._last_scroll_direction
            self._submit_at[seq] = time.monotonic()
            self._inflight.add(seq)
        self._emit_collection_status()

    def _on_ocr_sequenced(self, seq: int, result) -> None:
        image = self._pending_images.pop(seq, None)
        self._inflight.discard(seq)
        started = self._submit_at.pop(seq, None)
        if started is not None:
            self._ocr_durations.append(time.monotonic() - started)
            del self._ocr_durations[:-8]
        if seq not in self._frame_dirs:
            # A result from an *earlier* collection (aborted with 清除/关闭, or
            # finished by the drain timeout) arriving after a new session
            # started. Its seq is meaningless now; merging it would splice
            # old content into the fresh transcript.
            self._log("忽略上一轮采集迟到的识别结果")
            return
        direction = self._frame_dirs.pop(seq, 1)
        stitcher = self._stitcher
        if stitcher is None:
            # Only reachable through the drain timeout; say so instead of
            # pretending the frame never existed.
            self._log("采集已收尾，忽略迟到的一帧识别结果")
            return
        if self._chat_bounds and result.chat_bounds is None and image is not None:
            result = recognize_chat_layout(result, image, known_bounds=self._chat_bounds)
        observation = result.conversation
        if self._different_conversation(observation):
            self._last_frame = None
            self._collecting = False
            if self._ocr_worker is not None:
                self._ocr_worker.clear_queue()
            self.collection_hint.emit("画面切换到了另一段会话，已保留原会话的记录")
            self._finish_collection()
            return
        self._observe_conversation(observation)
        if self._settings.vision_enabled and image is not None and (result.chat_bounds or not self._chat_bounds):
            self._confirmed_image = image, result.chat_bounds
        if result.chat_bounds:
            self._chat_bounds = result.chat_bounds
            if isinstance(self._session, CaptureSession):
                self._session.set_chat_bounds(result.chat_bounds)
        page = page_lines_from_ocr(result)
        report = stitcher.add_page(page, direction=direction)
        if page:
            self._last_recognized_seq = seq
        if report.kind == "break":
            self.collection_hint.emit(
                "检测到断点：这里没有可靠重叠，建议向上滚回补采，或结束后手动补一行"
            )
            self._log(
                f"断点 · 第 {report.page} 屏 · 插入 {report.inserted_after} 行"
            )
        elif report.kind != "noop":
            self._log(
                f"拼接 · 第 {report.page} 屏 · 匹配 {report.matched_lines} 行 · "
                f"新增 {report.inserted_before + report.inserted_middle + report.inserted_after} 行"
            )
        self._emit_collection_status()
        if self._collection_stopping:
            self._check_drained()

    def _on_ocr_sequenced_failed(self, seq: int, message: str, _timestamp: float) -> None:
        self._pending_images.pop(seq, None)
        self._inflight.discard(seq)
        self._submit_at.pop(seq, None)
        self._frame_dirs.pop(seq, None)
        self._log(message)
        if self._collection_stopping:
            self._check_drained()

    def _on_queue_full(self, dropped: int) -> None:
        self._collection_dropped = max(self._collection_dropped, int(dropped))
        self.collection_hint.emit("滚动太快，画面队列已满：请放慢滚动速度")
        self._emit_collection_status()

    def _on_collection_state(self, state: str) -> None:
        self._collection_state_label = state
        self.collection_state_changed.emit(state)
        self._emit_collection_status()
        if state == STATE_COLLECTING:
            self._set_state("采集中")
        elif state == STATE_PAUSED:
            self._set_state("采集暂停")
        elif state == STATE_STOPPING:
            self._set_state("收尾")

    def _on_collection_paused(self, reason: str) -> None:
        self.collection_hint.emit(f"采集已暂停：{reason}")

    def _on_collection_resumed(self) -> None:
        self.collection_hint.emit("已恢复采集")

    def _on_collection_source_ended(self, reason: str) -> None:
        self._log(reason)
        self.stop_collection()
        self._window_selection = None
        self._region = None

    def _on_collection_error(self, message: str) -> None:
        self._log(message)
        self.collection_hint.emit(message)

    def _on_collection_status(self, _snapshot: dict | None = None) -> None:
        self._emit_collection_status()

    def _emit_collection_status(self) -> None:
        stitcher = self._stitcher
        worker = self._ocr_worker
        snapshot = {
            "collecting": self._collecting,
            "stopping": self._collection_stopping,
            "session_state": self._collection_state_label,
            "frames": self._collection_frames,
            "queued": worker.pending_count if worker is not None else 0,
            "inflight": len(self._inflight),
            "dropped": self._collection_dropped,
            "lines": len(stitcher.lines) if stitcher is not None else 0,
            "breakpoints": len(stitcher.breakpoints) if stitcher is not None else 0,
        }
        self.collection_status.emit(snapshot)

    def _abort_collection(self) -> None:
        """Discard an ongoing collection (clear / shutdown)."""
        was_collecting = self.collecting
        if self._drain_timer is not None:
            self._drain_timer.stop()
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
        self._collecting = False
        self._collection_stopping = False
        self._stitcher = None
        self._last_frame = None
        self._pending_images.clear()
        self._confirmed_image = None
        self._frame_dirs.clear()
        self._inflight.clear()
        self._submit_at.clear()
        if was_collecting:
            self._on_collection_state(STATE_IDLE)

    # ---------------------------------------------------------------- analyze
    def analyze(self, text: str, *, thinking: bool | None = None) -> None:
        if self._closing:
            return
        if self.collecting:
            self._status("正在连续采集，先点「结束采集」再解读")
            return
        if self._busy:
            self._status("正在解读，请稍等")
            return
        if self._capturing:
            self._status("正在读取画面，请稍等")
            return
        if self._worker is not None and self._worker.isRunning():
            self._status("正在结束上一轮解读，请稍等")
            return
        text = (text or "").strip()
        images = tuple(self._images) if self._settings.vision_enabled else ()
        if not text and not images:
            self._status("没有可解读的内容：请粘贴聊天记录，或先读取一张画面")
            return

        max_chars = max(2000, int(self._settings.long_text_max_chars))
        if len(text) > max_chars:
            self._log(f"长文将分段归纳 · 单次上下文预算 {max_chars:,} 字")
        deep = self._settings.thinking_enabled if thinking is None else bool(thinking)
        try:
            token_limit = int(self._settings.llm_max_tokens)
            if deep:
                token_limit = max(token_limit, 8000)
            client = self._make_client(token_limit)
        except LLMNotConfiguredError as exc:
            self._status(str(exc))
            self._set_state("错误")
            return
        except Exception as exc:
            self._status(f"模型客户端初始化失败：{exc}")
            self._set_state("错误")
            return

        request = ConversationRequest(text, max_chars, deep, images, self._conversation)
        self._decode_token += 1
        token = self._decode_token
        self._last_text_chars = len(text)
        self._busy = True
        self._set_busy(True)
        self._set_state("解读中")
        self._llm_started = time.monotonic()
        self._stage("capture", "done")
        self._stage("text", "done")
        if images:
            self._stage("vision", "active")
        else:
            self._stage("vision", "done")
        self._stage("decode", "active")
        self.llm_activity.emit(True)
        self._log(
            f"开始按需解读 · {len(text)} 字 · {len(images)} 张画面 · "
            f"{'深度思考' if deep else '快速模式'}"
        )
        self.analysis_started.emit()
        if deep:
            self.thinking_started.emit()

        worker = ConversationWorker(token, client, request, self)
        worker.reasoning.connect(self._on_reasoning)
        worker.status.connect(self._on_request_status)
        worker.completed.connect(self._on_decode_completed)
        worker.failed.connect(self._on_decode_failed)
        worker.finished.connect(self._retire_agent_worker)
        self._worker = worker
        worker.start()
        self._status("正在准备会话分析…")

    def _make_client(self, token_limit: int):
        if self._mock_llm:
            return MockLLMClient()
        if self._client_factory is not None:
            return self._client_factory()
        return create_llm_client(self._settings, max_tokens=token_limit)

    def _on_reasoning(self, token: int, delta: str) -> None:
        if token != self._decode_token:
            return
        self.thinking_delta.emit(delta)

    def _on_request_status(self, token: int, phase: str) -> None:
        if token != self._decode_token:
            return
        messages = {
            "encoding": "正在压缩画面…",
            "requesting": "请求已发出，等待模型响应",
            "first_token": "模型开始输出",
            "parsing": "解析结构化结果",
            "fallback": "流式不可用，改为普通请求",
        }
        if phase.startswith("history:"):
            message = f"正在归纳历史对话（{phase.split(':', 1)[1]}）"
            self._log(message)
            self._status(message)
        elif phase in messages:
            self._log(messages[phase])

    def _on_decode_completed(self, token: int, result) -> None:
        if token != self._decode_token:
            return
        elapsed = time.monotonic() - getattr(self, "_llm_started", time.monotonic())
        self._busy = False
        self._set_busy(False)
        self.llm_activity.emit(False)
        for stage in ("vision", "decode"):
            self._stage(stage, "done")
        self._last_latency = elapsed
        self._set_state("已完成")
        self._log(f"解读完成 · {elapsed:.1f}s · Schema ✓")
        self.last_update.emit(now_ts())
        self._publish_metrics()
        self.analysis_completed.emit(result)
        self._status(f"解读完成 · {elapsed:.1f}s · 已生成 {len(result.suggested_replies)} 条回复")

    def _on_decode_failed(self, token: int, message: str) -> None:
        if token != self._decode_token:
            return
        self._busy = False
        self._set_busy(False)
        self.llm_activity.emit(False)
        self._stage("decode", "error")
        self._set_state("错误")
        self._log(f"解读失败 · {message}")
        self._status(message)
        self.analysis_failed.emit(message)

    def _retire_agent_worker(self) -> None:
        worker = self.sender()
        if worker is self._worker:
            self._worker = None
        if worker is not None:
            worker.deleteLater()

    # ---------------------------------------------------------------- helpers
    def _set_state(self, state: str) -> None:
        self._state = state
        self.state_changed.emit(state)
        self._publish_metrics()

    def _set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.busy_changed.emit(self._busy)

    def _status(self, message: str) -> None:
        self.status_message.emit(message)

    def _log(self, message: str) -> None:
        self.pipeline_log.emit(f"{format_clock(now_ts())}  {message}")

    def _stage(self, name: str, state: str) -> None:
        self.stage_changed.emit(name, state)

    def _reset_stages(self) -> None:
        for name, _label in STAGES:
            self.stage_changed.emit(name, "idle")

    def _publish_metrics(self) -> None:
        self.metrics_updated.emit(
            {
                "state": self._state,
                "images": len(self._images),
                "text_chars": self._last_text_chars,
                "latency": self._last_latency,
                "vision": bool(self._settings.vision_enabled),
                "thinking": bool(self._settings.thinking_enabled),
                "max_chars": int(self._settings.long_text_max_chars),
                "collecting": self.collecting,
                "collect_lines": len(self._stitcher.lines) if self._stitcher else 0,
            }
        )

    def begin_shutdown(self) -> tuple[QThread, ...]:
        """Stop new work and return threads that must finish before exit."""
        if not self._closing:
            self._closing = True
            self._close_window_reader()
            self._decode_token += 1
            self._capture_token += 1
            self._pending_capture_token = -1
            self._single_frame = None
            self._abort_collection()
            if self._worker is not None:
                self._worker.requestInterruption()
            if self._ocr_worker is not None:
                self._ocr_worker.stop()
            if self._capture is not None:
                self._capture.close()
                self._capture = None
        return tuple(worker for worker in (self._worker, self._ocr_worker)
                     if worker is not None and worker.isRunning())

    def shutdown(self) -> None:
        for worker in self.begin_shutdown():
            worker.wait()

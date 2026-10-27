"""On-demand conversation decoder.

No screen monitoring, no debounce, no repeated LLM calls: the user explicitly
captures one or more screens, optionally pastes a long conversation, then asks
for a single decode. This is the v2 product path.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QThread, Signal

from app.capture.screen_capture import CaptureError, ScreenCapture
from app.analysis.workers import OCRWorkerThread
from app.llm.client import MockLLMClient
from app.llm.prompt import build_long_user_prompt, build_system_prompt
from app.llm.provider import (
    LLMNotConfiguredError,
    analyze_with_client,
    create_llm_client,
)
from app.llm.vision import encode_image_data_url
from app.models.schemas import ScreenshotFrame, ScreenRegion
from app.ocr.engine import build_engine
from app.utils.time import format_clock, now_ts

logger = logging.getLogger("ocr_chat.decoder")

STAGES = (
    ("capture", "读取画面"),
    ("text", "整理文本"),
    ("vision", "画面理解"),
    ("decode", "语义解读"),
)


class _DecodeWorker(QThread):
    reasoning = Signal(int, str)
    status = Signal(int, str)
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, token, client, system_prompt, user_prompt, images, thinking, parent=None):
        super().__init__(parent)
        self._token = token
        self._client = client
        self._system = system_prompt
        self._user = user_prompt
        self._images = tuple(images or ())
        self._thinking = bool(thinking)

    def run(self) -> None:
        try:
            result = analyze_with_client(
                self._client,
                self._system,
                self._user,
                images=self._images or None,
                on_reasoning=(
                    (lambda delta: self.reasoning.emit(self._token, delta))
                    if self._thinking
                    else None
                ),
                on_status=lambda phase: self.status.emit(self._token, phase),
            )
            if self._images:
                result.vision_used = True
            self.completed.emit(self._token, result)
        except Exception as exc:  # friendly message already where possible
            logger.warning("decode failed: %s", exc)
            self.failed.emit(self._token, str(exc))


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
    analysis_started = Signal()
    thinking_started = Signal()
    thinking_delta = Signal(str)
    analysis_completed = Signal(object)
    analysis_failed = Signal(str)
    last_update = Signal(float)
    metrics_updated = Signal(dict)
    cleared = Signal()

    def __init__(
        self,
        settings,
        *,
        mock_llm: bool = False,
        ocr_engine_factory=None,
        client_factory=None,
        capture_factory=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._mock_llm = bool(mock_llm)
        self._ocr_factory = ocr_engine_factory
        self._client_factory = client_factory
        self._capture_factory = capture_factory
        self._capture = None
        self._ocr_worker = None
        self._region: ScreenRegion | None = None
        self._images: list[str] = []
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

    def set_region(self, region: ScreenRegion) -> None:
        self._region = region

    def clear_images(self, *, announce: bool = True) -> None:
        self._images.clear()
        self.images_changed.emit(0)
        if announce:
            self._log("已清空附带画面")

    def clear(self) -> None:
        self._decode_token += 1
        self._capture_token += 1
        self._pending_capture_token = -1
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
        if self._capturing:
            self._status("正在读取上一张画面，请稍等")
            return
        if self._busy:
            self._status("正在解读，请等这次结果出来再读取画面")
            return
        if region is not None:
            self._region = region
        if self._region is None:
            self._status("请先框选一个聊天区域")
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

    def capture_from_image(self, image) -> None:
        """Test / clipboard helper: decode an already captured RGB array."""
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

        if self._settings.vision_enabled and frame.image is not None:
            url = encode_image_data_url(
                frame.image,
                max_side=self._settings.vision_max_side,
                quality=self._settings.vision_quality,
            )
            if url:
                self._add_image(url)
            else:
                self._log("画面压缩失败，本次只分析文本")

        self._ensure_ocr()
        self._ocr_worker.submit(frame)
        self._status("正在本地识别文字；可同时把长聊天记录粘贴到左侧")

    def _ensure_ocr(self) -> None:
        if self._ocr_worker is not None:
            return
        factory = self._ocr_factory or build_engine
        worker = OCRWorkerThread(factory)
        worker.engine_ready.connect(self._on_engine_ready)
        worker.engine_failed.connect(self._on_engine_failed)
        worker.ocr_completed.connect(self._on_ocr_completed)
        worker.ocr_failed.connect(self._on_ocr_failed)
        self._ocr_worker = worker
        self.engine_status_changed.emit("正在加载 OCR 模型…")
        worker.start()

    def _on_engine_ready(self) -> None:
        self.engine_status_changed.emit("OCR 模型就绪")
        self._log("OCR 模型就绪 · 只在读取画面时使用")

    def _on_engine_failed(self, message: str) -> None:
        worker, self._ocr_worker = self._ocr_worker, None
        if worker is not None:
            worker.wait(500)
            worker.deleteLater()
        self._capturing = False
        self._set_busy(False)
        self.ocr_activity.emit(False)
        self._stage("capture", "error")
        self._set_state("错误")
        self._status(message)
        self._log(message)

    def _on_ocr_completed(self, result) -> None:
        if self._pending_capture_token != self._capture_token:
            return
        # Preserve line structure for long conversations. The normalized
        # text is optimized for diffing and collapses newlines, which would
        # turn a multi-speaker chat into one unreadable line.
        line_text = "\n".join(
            line.text.strip() for line in getattr(result, "lines", []) if line.text.strip()
        )
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
        self._capturing = False
        self._set_busy(False)
        self.ocr_activity.emit(False)
        self._stage("capture", "error")
        self._set_state("错误")
        self._status(message)
        self._log(message)

    def _add_image(self, url: str) -> None:
        if not url or url in self._images:
            return
        limit = max(1, int(self._settings.max_screenshots))
        self._images.append(url)
        while len(self._images) > limit:
            self._images.pop(0)
        self.images_changed.emit(len(self._images))
        self._log(f"画面已附带 · 共 {len(self._images)} 张（表情包/贴纸可被视觉理解）")

    # ---------------------------------------------------------------- analyze
    def analyze(self, text: str, *, thinking: bool | None = None) -> None:
        if self._busy:
            self._status("正在解读，请稍等")
            return
        if self._capturing:
            self._status("正在读取画面，请稍等")
            return
        text = (text or "").strip()
        images = list(self._images) if self._settings.vision_enabled else []
        if not text and not images:
            self._status("没有可解读的内容：请粘贴聊天记录，或先读取一张画面")
            return

        max_chars = max(2000, int(self._settings.long_text_max_chars))
        truncated = len(text) > max_chars
        if truncated:
            text = text[-max_chars:]
            self._log(f"长文本超出 {max_chars} 字，保留最近部分")
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

        system = build_system_prompt(thinking_enabled=deep, vision=bool(images))
        user = build_long_user_prompt(
            text,
            image_count=len(images),
            thinking_enabled=deep,
            truncated=truncated,
        )
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

        worker = _DecodeWorker(
            token,
            client,
            system,
            user,
            images,
            deep,
            self,
        )
        worker.reasoning.connect(self._on_reasoning)
        worker.status.connect(self._on_request_status)
        worker.completed.connect(self._on_decode_completed)
        worker.failed.connect(self._on_decode_failed)
        self._worker = worker
        worker.start()
        self._status("请求已发出，正在理解这段对话…")

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
        if phase in messages:
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
        self._cleanup_worker()

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
        self._cleanup_worker()

    def _cleanup_worker(self) -> None:
        worker, self._worker = self._worker, None
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
            }
        )

    def shutdown(self) -> None:
        self._decode_token += 1
        self._capture_token += 1
        if self._worker is not None:
            if not self._worker.wait(1500):
                self._worker.terminate()
                self._worker.wait(500)
            self._worker = None
        if self._ocr_worker is not None:
            self._ocr_worker.stop()
            if not self._ocr_worker.wait(2500):
                self._ocr_worker.terminate()
                self._ocr_worker.wait(500)
            self._ocr_worker = None
        if self._capture is not None:
            try:
                self._capture.close()
            except Exception:
                pass
            self._capture = None

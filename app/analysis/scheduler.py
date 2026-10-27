"""Realtime pipeline scheduler (the heart of the product).

    Timer -> Capture -> OCR(worker, latest-only) -> Normalize -> Fingerprint
      -> Change? -> Context update -> Debounce -> LLM(worker, max 1 active,
         stale results dropped by generation) -> Pydantic -> UI signals

Lives on the GUI thread and only does light orchestration; OCR and HTTP
run on dedicated QThread workers. All state (state machine, diff tracker,
context) is touched exclusively from the GUI thread via queued signals.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtCore import QObject, QTimer, Signal

from app.analysis.workers import LLMWorkerThread, OCRWorkerThread
from app.capture.frame_gate import FrameGate
from app.capture.monitor import RegionMonitor
from app.context.manager import ContextManager
from app.llm.client import MockLLMClient
from app.llm.prompt import build_system_prompt, build_user_prompt
from app.llm.provider import LLMNotConfiguredError, create_llm_client
from app.models.schemas import OCRResult, ScreenRegion
from app.ocr.diff import ChangeKind, TextDiffTracker, fingerprint
from app.ocr.engine import build_engine
from app.ocr.normalize import count_effective_chars
from app.utils.time import format_clock, now_ts

logger = logging.getLogger("ocr_chat.scheduler")


class AppState(Enum):
    IDLE = auto()
    SELECTING_REGION = auto()
    MONITORING = auto()
    OCR_PROCESSING = auto()
    WAITING_DEBOUNCE = auto()
    ANALYZING = auto()
    SHOWING_RESULT = auto()
    PAUSED = auto()
    ERROR = auto()


STATE_TEXT = {
    AppState.IDLE: "未开始",
    AppState.SELECTING_REGION: "选择区域中",
    AppState.MONITORING: "监控中",
    AppState.OCR_PROCESSING: "OCR 中",
    AppState.WAITING_DEBOUNCE: "等待文本稳定",
    AppState.ANALYZING: "AI 分析中",
    AppState.SHOWING_RESULT: "分析完成",
    AppState.PAUSED: "暂停",
    AppState.ERROR: "错误",
}


@dataclass
class _AnalysisJob:
    generation: int
    system_prompt: str
    user_prompt: str
    client: object
    images: tuple
    vision_options: tuple[int, int]
    thinking_enabled: bool
    fingerprint: str
    is_override: bool


class PipelineScheduler(QObject):
    # state / status
    state_changed = Signal(str)          # readable state text
    status_message = Signal(str)         # transient status (errors, hints)

    # region / capture
    region_changed = Signal(object)      # ScreenRegion | None

    # OCR
    ocr_text_updated = Signal(str, str)  # (normalized text, raw text)
    ocr_confidence_updated = Signal(float)
    ocr_activity = Signal(bool)          # True while an OCR pass runs
    engine_status_changed = Signal(str)  # "正在加载 OCR 模型…" etc.

    # context
    context_changed = Signal(object)     # ConversationContext

    # analysis
    analysis_started = Signal()
    analysis_completed = Signal(object)  # AnalysisResult
    analysis_failed = Signal(str)
    llm_activity = Signal(bool)
    cleared = Signal()

    # observability
    metrics_updated = Signal(dict)
    last_update = Signal(float)          # timestamp of last completed analysis
    pipeline_log = Signal(str)           # formatted timeline entry
    stage_changed = Signal(str, str)     # stage name, state ("idle"/"active"/"done"/"error")
    frame_preview = Signal(object)       # latest captured RGB frame (numpy) or None

    # thinking / streaming
    thinking_started = Signal()
    thinking_delta = Signal(str)

    def __init__(
        self,
        settings,
        *,
        mock_llm: bool = False,
        llm_factory=None,
        ocr_engine_factory=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._mock_llm = mock_llm
        self._llm_factory = llm_factory
        self._ocr_engine_factory = ocr_engine_factory or (lambda: build_engine())

        self._region: ScreenRegion | None = settings.stored_region
        self._context = ContextManager(
            max_messages=settings.max_context_messages,
            max_chars=settings.max_context_chars,
        )
        self._diff = TextDiffTracker()
        self._state = AppState.IDLE

        self._generation = 0
        self._active_llm_gen: int | None = None
        self._pending_llm: _AnalysisJob | None = None
        self._inflight_fp: str | None = None

        self._latest_ocr_text = ""
        self._latest_raw_text = ""
        self._user_override: str | None = None
        self._baseline_pending = False
        self._pending_start = False
        self._engine_ready = False
        self._engine_failed = False

        self._latest_frame = None
        self._frame_gate = FrameGate()

        self._last_ocr_latency_s: float | None = None
        self._last_llm_latency_s: float | None = None
        self._llm_started_ts: float | None = None
        self._last_analysis_ts: float | None = None

        # capture
        self._monitor = RegionMonitor(self._region, settings.capture_interval_ms, self)
        self._monitor.frame_captured.connect(self._on_frame)
        self._monitor.capture_error.connect(self._on_capture_error)

        # OCR worker (engine init happens inside the thread)
        self._ocr_worker = OCRWorkerThread(self._ocr_engine_factory, self)
        self._ocr_worker.engine_ready.connect(self._on_engine_ready)
        self._ocr_worker.engine_failed.connect(self._on_engine_failed)
        self._ocr_worker.ocr_started.connect(self._on_ocr_started)
        self._ocr_worker.ocr_completed.connect(self._on_ocr_completed)
        self._ocr_worker.ocr_failed.connect(self._on_ocr_failed)
        self._ocr_worker.start()
        self.engine_status_changed.emit("正在加载 OCR 模型…")

        # LLM worker
        self._llm_worker = LLMWorkerThread(self)
        self._llm_worker.llm_completed.connect(self._on_llm_completed)
        self._llm_worker.llm_failed.connect(self._on_llm_failed)
        self._llm_worker.llm_latency.connect(self._on_llm_latency)
        self._llm_worker.llm_reasoning.connect(self._on_llm_reasoning)
        self._llm_worker.llm_status.connect(self._on_llm_status)
        self._llm_worker.start()

        # debounce (single-shot)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(settings.debounce_ms)
        self._debounce.timeout.connect(self._on_debounce_fired)

        self._set_state(AppState.IDLE)

    # ---- public API ---------------------------------------------------------

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def region(self) -> ScreenRegion | None:
        return self._region

    @property
    def is_monitoring(self) -> bool:
        return self._state in (
            AppState.MONITORING,
            AppState.OCR_PROCESSING,
            AppState.WAITING_DEBOUNCE,
            AppState.ANALYZING,
            AppState.SHOWING_RESULT,
        )

    @property
    def user_override(self) -> str | None:
        return self._user_override

    def start_monitoring(self) -> None:
        if self._region is None:
            self._set_status("请先选择监控区域")
            return
        self._start(take_baseline=True)

    def pause(self) -> None:
        self._monitor.stop()
        self._debounce.stop()
        self._pending_start = False
        self._generation += 1  # invalidate in-flight / pending analysis
        self._active_llm_gen = None
        self._pending_llm = None
        self._reset_stages()
        self._log("已暂停监控")
        self._set_state(AppState.PAUSED)
        self.llm_activity.emit(False)
        logger.info("monitoring paused (generation=%s)", self._generation)

    def resume(self) -> None:
        if self._region is None:
            self._set_status("请先选择监控区域")
            return
        self._start(take_baseline=True)

    def set_region_and_restart(self, region: ScreenRegion, resume_after: bool) -> None:
        """After the user confirms a (re)selection: save, reset OCR state, restart."""
        self.pause()
        self._region = region
        try:
            self._settings.region = region.model_dump()
            self._settings.save()
        except Exception as exc:
            logger.warning("failed to persist region: %s", exc)
        self._monitor.set_region(region)
        self._context.clear()
        self.context_changed.emit(self._context.get_context())
        self._diff.reset()
        self._frame_gate.reset()
        self._latest_frame = None
        self.frame_preview.emit(None)
        self._reset_stages()
        self._user_override = None
        self._latest_ocr_text = ""
        self._latest_raw_text = ""
        self.ocr_text_updated.emit("", "")
        self.region_changed.emit(region)
        self._log("已更新监控区域")
        self._set_status("已选择新区域")
        if resume_after:
            self.resume()

    def clear_context(self) -> None:
        self._context.clear()
        self.context_changed.emit(self._context.get_context())
        self._diff.reset_baseline(self._latest_ocr_text)
        self._user_override = None
        self._reset_stages()
        self._log("上下文已清空")
        self._set_status("上下文已清空")
        self.cleared.emit()

    def set_user_override(self, text: str) -> None:
        self._user_override = text

    def notify(self, message: str) -> None:
        """UI-facing transient status message."""
        self._set_status(message)

    def analyze_now(self, text: str | None = None, force: bool = True) -> None:
        """Explicit (re)analysis - used by the OCR editor 'apply' button."""
        if text is not None:
            self._user_override = text
        source = self._user_override or self._latest_ocr_text
        if not source.strip():
            self._set_status("没有可分析文本")
            return
        if count_effective_chars(source) < self._settings.min_ocr_chars:
            self._set_status("文本过短，暂不分析")
            return
        self._debounce.stop()
        fp = fingerprint(source)
        if not force and self._diff.is_current_analyzed(source):
            self._set_state(AppState.MONITORING)
            return
        self._trigger_analysis(source, fp, is_override=self._user_override is not None)

    def apply_settings(self, settings) -> None:
        self._settings = settings
        self._monitor.set_interval(settings.capture_interval_ms)
        self._debounce.setInterval(settings.debounce_ms)
        self._context.set_limits(settings.max_context_messages, settings.max_context_chars)
        self._frame_gate.reset()
        self._log(
            "设置已应用 · "
            f"{'视觉开启' if settings.vision_enabled else '文本分析'} · "
            f"{'思考开启' if settings.thinking_enabled else '思考关闭'}"
        )

    def shutdown(self) -> None:
        self._monitor.close()
        self._debounce.stop()
        self._ocr_worker.stop()
        self._llm_worker.stop()
        self._ocr_worker.wait(5000)
        self._llm_worker.wait(5000)

    # ---- capture ------------------------------------------------------------

    def _on_frame(self, frame) -> None:
        if self._state == AppState.PAUSED:
            return
        self._latest_frame = frame
        if self._settings.fast_frame_gate and self._frame_gate.is_duplicate(frame.image):
            return
        if frame.image is not None:
            self.frame_preview.emit(frame.image)
        if not self._engine_ready:
            if self._engine_failed:
                self._set_status("OCR 引擎不可用，无法监控")
                return
            return  # engine still loading; frames are not queued
        self._stage("ocr", "active")
        self._ocr_worker.submit(frame)
        if self._state in (AppState.MONITORING, AppState.SHOWING_RESULT):
            self._set_state(AppState.OCR_PROCESSING)

    def _on_capture_error(self, message: str) -> None:
        logger.warning("capture error: %s", message)
        self._log(f"截图失败 · {message}")
        self._set_status(f"截图失败：{message}")

    # ---- OCR -----------------------------------------------------------------

    def _on_engine_ready(self) -> None:
        self._engine_ready = True
        self.engine_status_changed.emit("OCR 模型就绪")
        self._log("OCR 模型就绪")
        self._set_status("OCR 模型就绪")
        if self._pending_start:
            self._pending_start = False
            self._start(take_baseline=True)

    def _on_engine_failed(self, message: str) -> None:
        self._engine_failed = True
        self._pending_start = False
        logger.error("OCR engine failed: %s", message)
        self.engine_status_changed.emit("OCR 引擎初始化失败")
        self._log(f"OCR 引擎不可用 · {message}")
        self._set_status(message)
        self._set_state(AppState.ERROR)

    def _on_ocr_started(self, frame_ts: float) -> None:
        self.ocr_activity.emit(True)
        self._stage("ocr", "active")

    def _on_ocr_completed(self, result: OCRResult) -> None:
        self.ocr_activity.emit(False)
        if self._state == AppState.PAUSED:
            return
        self._last_ocr_latency_s = now_ts() - result.timestamp if result.timestamp else None
        self._publish_metrics()
        self._stage("ocr", "done")

        if result.error:
            self._log(f"OCR 错误 · {result.error}")
            self._set_status(f"OCR 错误：{result.error}")
            self._reset_stages(keep_ocr=True)
            self._set_state(AppState.MONITORING)
            return

        self._latest_raw_text = result.raw_text
        self.ocr_confidence_updated.emit(result.confidence)

        text = result.normalized_text
        if not text:
            self._reset_stages(keep_ocr=True)
            self._set_state(AppState.MONITORING)
            return

        kind = self._diff.update(text, result.lines)

        if self._baseline_pending:
            # first snapshot after (re)start: new baseline, never analyzed
            self._baseline_pending = False
            self._on_baseline(text, result)
            self._reset_stages(keep_ocr=True)
            self._set_state(AppState.MONITORING)
            return

        if kind == ChangeKind.SAME:
            self._reset_stages(keep_ocr=True)
            self._set_state(AppState.MONITORING)
            return

        if kind == ChangeKind.SCROLL_ONLY:
            # pure scroll: refresh display + context, do NOT call the LLM
            self._latest_ocr_text = text
            self._user_override = None
            self.ocr_text_updated.emit(text, self._latest_raw_text)
            self._update_context_from_ocr(result)
            self._log("纯滚动 · 已更新上下文（未触发模型）")
            self._stage("diff", "done")
            self._set_status("上下文已随滚动更新（无新消息，不触发分析）")
            self._set_state(AppState.MONITORING)
            return

        # text changed -> update context immediately, then debounce the LLM call
        latency_ms = (self._last_ocr_latency_s or 0.0) * 1000
        self._log(f"检测到文本变化 · {len(result.lines)} 行 · OCR {latency_ms:.0f}ms")
        self._latest_ocr_text = text
        self._user_override = None  # fresh OCR content supersedes a pending edit
        self.ocr_text_updated.emit(text, self._latest_raw_text)
        self._update_context_from_ocr(result)
        self._stage("diff", "done")
        self._stage("debounce", "active")
        self._log(f"等待文本稳定 {self._debounce.interval()}ms")
        self._set_status("检测到新内容")
        self._set_state(AppState.WAITING_DEBOUNCE)
        self._debounce.start()
        logger.info("text changed, debouncing (%sms)", self._debounce.interval())

    def _on_ocr_failed(self, message: str, frame_ts: float) -> None:
        self.ocr_activity.emit(False)
        if self._state == AppState.PAUSED:
            return
        logger.warning("OCR failed: %s", message)
        self._log(f"OCR 失败 · {message}")
        self._set_status(f"OCR 错误：{message}")
        self._reset_stages()
        # keep monitoring; the next frame retries
        self._set_state(AppState.MONITORING)

    def _on_baseline(self, text: str, result: OCRResult) -> None:
        self._latest_ocr_text = text
        self._user_override = None
        self.ocr_text_updated.emit(text, self._latest_raw_text)
        self._update_context_from_ocr(result)
        self._log(f"已建立监控基准 · {len(result.lines)} 行")
        self._set_status("监控中（已建立新基准）")
        logger.info("baseline snapshot established")

    def _update_context_from_ocr(self, result: OCRResult) -> None:
        changed = self._context.update_from_ocr(
            lines=result.lines,
            region_width=float(self._region.width) if self._region else 0.0,
            timestamp=result.timestamp or now_ts(),
            speaker_heuristic=self._settings.speaker_heuristic,
        )
        if changed:
            self.context_changed.emit(self._context.get_context())

    # ---- debounce / analysis --------------------------------------------------

    def _on_debounce_fired(self) -> None:
        if self._state == AppState.PAUSED:
            return
        source = self._user_override or self._latest_ocr_text
        if not source.strip():
            self._reset_stages(keep_ocr=True)
            self._set_state(AppState.MONITORING)
            return
        if count_effective_chars(source) < self._settings.min_ocr_chars:
            self._log("文本过短，仅更新显示")
            self._reset_stages(keep_ocr=True)
            self._set_state(AppState.MONITORING)
            return
        fp = fingerprint(source)
        if self._diff.is_current_analyzed(source):
            logger.info("text already analyzed, skipping")
            self._reset_stages(keep_ocr=True)
            self._set_state(AppState.MONITORING)
            return
        self._stage("debounce", "done")
        self._trigger_analysis(source, fp, is_override=self._user_override is not None)

    def _trigger_analysis(self, text: str, fp: str, is_override: bool) -> None:
        self._generation += 1
        gen = self._generation

        try:
            client = self._make_client()
        except LLMNotConfiguredError as exc:
            self._log(f"分析未开始 · {exc}")
            self._set_status(str(exc))
            self.analysis_failed.emit(str(exc))
            self._reset_stages(keep_ocr=True)
            self._set_state(AppState.MONITORING)
            return

        context = self._context.get_context()
        thinking_enabled = bool(self._settings.thinking_enabled)
        image = getattr(self._latest_frame, "image", None) if self._latest_frame else None
        vision = bool(self._settings.vision_enabled and image is not None)
        images = (image,) if vision else ()

        system_prompt = build_system_prompt(
            thinking_enabled=thinking_enabled,
            vision=vision,
        )
        user_prompt = build_user_prompt(
            context,
            override_text=text if is_override else None,
            vision=vision,
            thinking_enabled=thinking_enabled,
        )

        job = _AnalysisJob(
            generation=gen,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            client=client,
            images=images,
            vision_options=(self._settings.vision_max_side, self._settings.vision_quality),
            thinking_enabled=thinking_enabled,
            fingerprint=fp,
            is_override=is_override,
        )

        if self._active_llm_gen is not None:
            # max_active_analysis = 1: hold the new request, supersede any pending
            self._pending_llm = job
            self._log(f"新请求排队 · generation #{gen}（最多 1 个在途）")
            logger.info("analysis queued behind in-flight request (gen %s)", gen)
        else:
            self._send_llm(job)

        self._stage("llm", "active")
        self._set_state(AppState.ANALYZING)
        self.analysis_started.emit()
        if thinking_enabled:
            self.thinking_started.emit()

    def _send_llm(self, job: _AnalysisJob) -> None:
        self._active_llm_gen = job.generation
        self._inflight_fp = job.fingerprint if not job.is_override else None
        self._llm_started_ts = now_ts()
        self.llm_activity.emit(True)
        self._llm_worker.submit(
            job.generation,
            job.system_prompt,
            job.user_prompt,
            job.client,
            images=job.images,
            vision_options=job.vision_options,
            thinking_enabled=job.thinking_enabled,
        )
        vision_note = " · 含画面" if job.images else ""
        self._log(f"请求模型 · generation #{job.generation}{vision_note}")
        logger.info("LLM request sent (gen %s)", job.generation)

    def _make_client(self):
        if self._mock_llm:
            return MockLLMClient()
        if self._llm_factory is not None:
            try:
                return self._llm_factory()
            except LLMNotConfiguredError:
                raise
            except Exception as exc:
                logger.exception("LLM client factory failed")
                raise LLMNotConfiguredError(f"LLM 客户端创建失败：{exc}") from exc
        return create_llm_client(self._settings)

    def _on_llm_completed(self, gen: int, result) -> None:
        self.llm_activity.emit(False)
        if gen != self._generation:
            logger.info("stale LLM result dropped (gen %s, current %s)", gen, self._generation)
            self._log(f"丢弃陈旧结果 · generation #{gen}")
            self._active_llm_gen = None
        elif gen == self._active_llm_gen:
            self._active_llm_gen = None
            if self._inflight_fp is not None:
                self._diff.mark_analyzed_by_fp(self._inflight_fp)
                self._inflight_fp = None
            self._last_analysis_ts = now_ts()
            self.last_update.emit(self._last_analysis_ts)
            self._stage("llm", "done")
            self._stage("ui", "done")
            if self._llm_started_ts is not None:
                latency = now_ts() - self._llm_started_ts
            else:
                latency = self._last_llm_latency_s or 0.0
            self._log(
                f"分析完成 · generation #{gen} · {latency:.1f}s · "
                f"Schema ✓ · {len(result.suggested_replies)} 条回复"
            )
            self._set_state(AppState.SHOWING_RESULT)
            self.analysis_completed.emit(result)
            logger.info("analysis result accepted (gen %s)", gen)
        self._drain_pending_llm()

    def _on_llm_failed(self, gen: int, message: str) -> None:
        self.llm_activity.emit(False)
        if gen != self._generation:
            logger.info("stale LLM failure dropped (gen %s)", gen)
            self._active_llm_gen = None
        elif gen == self._active_llm_gen:
            self._active_llm_gen = None
            self._inflight_fp = None
            self._log(f"分析失败 · generation #{gen} · {message}")
            self._stage("llm", "error")
            self._set_status(f"分析失败：{message}")
            self.analysis_failed.emit(message)
            # keep old analysis displayed; go back to monitoring for the
            # next valid text change (no retry loop)
            self._set_state(AppState.MONITORING)
        self._drain_pending_llm()

    def _on_llm_reasoning(self, gen: int, delta: str) -> None:
        if gen == self._generation and self._state != AppState.PAUSED:
            self.thinking_delta.emit(delta)

    def _on_llm_status(self, gen: int, status: str) -> None:
        if gen != self._generation:
            return
        messages = {
            "encoding": "正在压缩画面…",
            "requesting": "请求已发出，等待模型响应",
            "first_token": "模型开始输出",
            "parsing": "解析结构化结果",
            "fallback": "流式不可用，改为普通请求",
        }
        message = messages.get(status)
        if message:
            self._log(message)

    def _drain_pending_llm(self) -> None:
        if self._pending_llm is None:
            return
        job, self._pending_llm = self._pending_llm, None
        if job.generation == self._generation and self._state != AppState.PAUSED:
            self._send_llm(job)
            self._stage("llm", "active")
            self._set_state(AppState.ANALYZING)
        else:
            self._log(f"丢弃排队请求 · generation #{job.generation}")
            logger.info("superseded pending analysis dropped (gen %s)", job.generation)

    def _on_llm_latency(self, gen: int, seconds: float) -> None:
        if gen == self._generation:
            self._last_llm_latency_s = seconds
            self._publish_metrics()

    # ---- pipeline telemetry -------------------------------------------------

    def _log(self, message: str) -> None:
        self.pipeline_log.emit(f"{format_clock(now_ts())}  {message}")

    def _stage(self, stage: str, state: str) -> None:
        self.stage_changed.emit(stage, state)

    def _reset_stages(self, *, keep_ocr: bool = False) -> None:
        for stage in ("ocr", "diff", "debounce", "llm", "ui"):
            if keep_ocr and stage == "ocr":
                continue
            self._stage(stage, "idle")

    # ---- state / status / metrics ---------------------------------------------

    def _start(self, take_baseline: bool) -> None:
        if self._region is None:
            self._set_status("请先选择监控区域")
            return
        if self._engine_failed:
            self._set_status("OCR 引擎不可用，无法监控")
            return
        if not self._engine_ready:
            self._pending_start = True  # auto-start once the OCR model is loaded
            self._set_status("OCR 模型仍在加载，就绪后将自动开始监控…")
            return
        if take_baseline:
            self._baseline_pending = True
        self._frame_gate.reset()
        self._reset_stages()
        self._monitor.start(self._region)
        self._log("开始监控" + (" · 等待建立基准" if take_baseline else ""))
        self._set_state(AppState.MONITORING)
        self._set_status("监控中")
        logger.info("monitoring started (baseline=%s)", take_baseline)

    def _set_state(self, state: AppState) -> None:
        if state == self._state:
            return
        self._state = state
        self.state_changed.emit(STATE_TEXT[state])
        self._publish_metrics()

    def _set_status(self, message: str) -> None:
        self.status_message.emit(message)

    def _publish_metrics(self) -> None:
        self.metrics_updated.emit(
            {
                "state": STATE_TEXT.get(self._state, ""),
                "context_size": self._context.size,
                "context_chars": sum(len(m.content) for m in self._context.get_context().messages),
                "ocr_latency_s": self._last_ocr_latency_s,
                "llm_latency_s": self._last_llm_latency_s,
                "generation": self._generation,
                "last_update": format_clock(self._last_analysis_ts),
                "vision_enabled": bool(self._settings.vision_enabled),
                "thinking_enabled": bool(self._settings.thinking_enabled),
                "gate_skipped": self._frame_gate.skipped,
                "gate_processed": self._frame_gate.processed,
            }
        )

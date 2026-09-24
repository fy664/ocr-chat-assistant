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
from enum import Enum, auto

from PySide6.QtCore import QObject, QTimer, Signal

from app.analysis.workers import LLMWorkerThread, OCRWorkerThread
from app.capture.monitor import RegionMonitor
from app.context.manager import ContextManager
from app.llm.client import MockLLMClient
from app.llm.provider import LLMNotConfiguredError, create_llm_client
from app.llm.prompt import SYSTEM_PROMPT, build_user_prompt
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
        self._pending_llm: tuple | None = None
        self._inflight_fp: str | None = None

        self._latest_ocr_text = ""
        self._latest_raw_text = ""
        self._user_override: str | None = None
        self._baseline_pending = False
        self._pending_start = False
        self._engine_ready = False
        self._engine_failed = False

        self._last_ocr_latency_s: float | None = None
        self._last_llm_latency_s: float | None = None
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
        self._user_override = None
        self._latest_ocr_text = ""
        self._latest_raw_text = ""
        self.ocr_text_updated.emit("", "")
        self.region_changed.emit(region)
        self._set_status("已选择新区域")
        if resume_after:
            self.resume()

    def clear_context(self) -> None:
        self._context.clear()
        self.context_changed.emit(self._context.get_context())
        self._diff.reset_baseline(self._latest_ocr_text)
        self._user_override = None
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
        if not self._engine_ready:
            if self._engine_failed:
                self._set_status("OCR 引擎不可用，无法监控")
                return
            return  # engine still loading; frames are not queued
        self._ocr_worker.submit(frame)
        if self._state in (AppState.MONITORING, AppState.SHOWING_RESULT):
            self._set_state(AppState.OCR_PROCESSING)

    def _on_capture_error(self, message: str) -> None:
        logger.warning("capture error: %s", message)
        self._set_status(f"截图失败：{message}")

    # ---- OCR -----------------------------------------------------------------

    def _on_engine_ready(self) -> None:
        self._engine_ready = True
        self.engine_status_changed.emit("OCR 模型就绪")
        self._set_status("OCR 模型就绪")
        if self._pending_start:
            self._pending_start = False
            self._start(take_baseline=True)

    def _on_engine_failed(self, message: str) -> None:
        self._engine_failed = True
        self._pending_start = False
        logger.error("OCR engine failed: %s", message)
        self.engine_status_changed.emit("OCR 引擎初始化失败")
        self._set_status(message)
        self._set_state(AppState.ERROR)

    def _on_ocr_started(self, frame_ts: float) -> None:
        self.ocr_activity.emit(True)

    def _on_ocr_completed(self, result: OCRResult) -> None:
        self.ocr_activity.emit(False)
        if self._state == AppState.PAUSED:
            return
        self._last_ocr_latency_s = now_ts() - result.timestamp if result.timestamp else None
        self._publish_metrics()

        if result.error:
            self._set_status(f"OCR 错误：{result.error}")
            self._set_state(AppState.MONITORING)
            return

        self._latest_raw_text = result.raw_text
        self.ocr_confidence_updated.emit(result.confidence)

        text = result.normalized_text
        if not text:
            self._set_status("未识别到文字")
            self._set_state(AppState.MONITORING)
            return

        kind = self._diff.update(text, result.lines)

        if self._baseline_pending:
            # first snapshot after (re)start: new baseline, never analyzed
            self._baseline_pending = False
            self._on_baseline(text, result)
            self._set_state(AppState.MONITORING)
            return

        if kind == ChangeKind.SAME:
            self._set_state(AppState.MONITORING)
            return

        if kind == ChangeKind.SCROLL_ONLY:
            # pure scroll: refresh display + context, do NOT call the LLM
            self._latest_ocr_text = text
            self._user_override = None
            self.ocr_text_updated.emit(text, self._latest_raw_text)
            self._update_context_from_ocr(result)
            self._set_status("上下文已随滚动更新（无新消息，不触发分析）")
            self._set_state(AppState.MONITORING)
            return

        # text changed -> update context immediately, then debounce the LLM call
        self._latest_ocr_text = text
        self._user_override = None  # fresh OCR content supersedes a pending edit
        self.ocr_text_updated.emit(text, self._latest_raw_text)
        self._update_context_from_ocr(result)
        self._set_status("检测到新内容")
        self._set_state(AppState.WAITING_DEBOUNCE)
        self._debounce.start()
        logger.info("text changed, debouncing (%sms)", self._debounce.interval())

    def _on_ocr_failed(self, message: str, frame_ts: float) -> None:
        self.ocr_activity.emit(False)
        if self._state == AppState.PAUSED:
            return
        logger.warning("OCR failed: %s", message)
        self._set_status(f"OCR 错误：{message}")
        # keep monitoring; the next frame retries
        self._set_state(AppState.MONITORING)

    def _on_baseline(self, text: str, result: OCRResult) -> None:
        self._latest_ocr_text = text
        self._user_override = None
        self.ocr_text_updated.emit(text, self._latest_raw_text)
        self._update_context_from_ocr(result)
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
            self._set_state(AppState.MONITORING)
            return
        if count_effective_chars(source) < self._settings.min_ocr_chars:
            self._set_status("文本过短，仅更新显示")
            self._set_state(AppState.MONITORING)
            return
        fp = fingerprint(source)
        if self._diff.is_current_analyzed(source):
            logger.info("text already analyzed, skipping")
            self._set_state(AppState.MONITORING)
            return
        self._trigger_analysis(source, fp, is_override=self._user_override is not None)

    def _trigger_analysis(self, text: str, fp: str, is_override: bool) -> None:
        self._generation += 1
        gen = self._generation

        try:
            client = self._make_client()
        except LLMNotConfiguredError as exc:
            self._set_status(str(exc))
            self.analysis_failed.emit(str(exc))
            self._set_state(AppState.MONITORING)
            return

        context = self._context.get_context()
        if is_override:
            user_prompt = build_user_prompt(context, override_text=text)
        else:
            user_prompt = build_user_prompt(context)

        payload = (gen, SYSTEM_PROMPT, user_prompt, client, fp, is_override)

        if self._active_llm_gen is not None:
            # max_active_analysis = 1: hold the new request, supersede any pending
            self._pending_llm = payload
            logger.info("analysis queued behind in-flight request (gen %s)", gen)
        else:
            self._send_llm(payload)

        self._set_state(AppState.ANALYZING)
        self.analysis_started.emit()

    def _send_llm(self, payload: tuple) -> None:
        gen, system_prompt, user_prompt, client, fp, is_override = payload
        self._active_llm_gen = gen
        self._inflight_fp = fp if not is_override else None
        self.llm_activity.emit(True)
        self._llm_worker.submit(gen, system_prompt, user_prompt, client)
        logger.info("LLM request sent (gen %s)", gen)

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
            self._active_llm_gen = None
        elif gen == self._active_llm_gen:
            self._active_llm_gen = None
            if self._inflight_fp is not None:
                self._diff.mark_analyzed_by_fp(self._inflight_fp)
                self._inflight_fp = None
            self._last_analysis_ts = now_ts()
            self.last_update.emit(self._last_analysis_ts)
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
            self._set_status(f"分析失败：{message}")
            self.analysis_failed.emit(message)
            # keep old analysis displayed; go back to monitoring for the
            # next valid text change (no retry loop)
            self._set_state(AppState.MONITORING)
        self._drain_pending_llm()

    def _drain_pending_llm(self) -> None:
        if self._pending_llm is None:
            return
        payload, self._pending_llm = self._pending_llm, None
        if payload[0] == self._generation and self._state != AppState.PAUSED:
            self._send_llm(payload)
        else:
            logger.info("superseded pending analysis dropped (gen %s)", payload[0])

    def _on_llm_latency(self, gen: int, seconds: float) -> None:
        if gen == self._generation:
            self._last_llm_latency_s = seconds
            self._publish_metrics()

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
        self._monitor.start(self._region)
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
            }
        )

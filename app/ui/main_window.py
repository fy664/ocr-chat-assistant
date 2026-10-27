"""Main window: a two-column, always-on-top semantic analysis console.

Layout:
    header (brand, live state, settings)
    region strip + shortcut hint
    body
      left  : current chat editor + (image preview | pipeline timeline)
      right : collapsible reasoning trail + analysis cards + replies
    actions + status bar
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.analysis.scheduler import AppState
from app.capture.region_selector import RegionSelector
from app.ui.floating_panel import AnalysisCards, ReplyList
from app.ui.ocr_editor import OCREditor
from app.ui.panels import ImagePreview, PipelinePanel, ThinkingPanel
from app.ui.status_bar import AppStatusBar
from app.ui.styles import APP_QSS
from app.ui.widgets import (
    CYAN,
    GREEN,
    MUTED,
    TONE_COLORS,
    Backdrop,
    BrandMark,
    GlowDot,
    SectionCard,
    app_icon,
    crosshair_icon,
    pause_icon,
    set_tone,
    tone_for_state,
)

logger = logging.getLogger("ocr_chat.ui.main")


class MainWindow(QMainWindow):
    closed = Signal()

    def __init__(self, scheduler, settings, parent=None) -> None:
        super().__init__(parent)
        self._scheduler = scheduler
        self._settings = settings
        self._selector: RegionSelector | None = None
        self._was_monitoring_before_select = False
        self._thinking_active = False

        self.setWindowTitle("言外 · 旧版实时窗口（未启用）")
        self.setMinimumSize(760, 680)
        self.resize(860, 900)
        self._fit_to_screen()
        self._apply_on_top(settings.always_on_top)
        self.setStyleSheet(APP_QSS)
        try:
            self.setWindowIcon(app_icon())
        except Exception:  # pragma: no cover - icon is cosmetic
            logger.debug("window icon unavailable", exc_info=True)

        central = Backdrop()
        central.setObjectName("backdrop")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 8)
        root.setSpacing(9)

        root.addLayout(self._build_header())
        root.addWidget(self._build_region_strip())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addLayout(self._build_left_column(), 5)
        body.addLayout(self._build_right_column(), 6)
        root.addLayout(body, 1)

        root.addLayout(self._build_actions())

        self._status_bar = AppStatusBar()
        self.setStatusBar(self._status_bar)

        self._shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self._shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut.activated.connect(self._on_select_region)

        self._connect_scheduler()
        self._apply_ui_settings()
        self._refresh_from_scheduler()

    # ---- building blocks --------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(11)

        header.addWidget(BrandMark(40))

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(1)
        title = QLabel("言外")
        title.setObjectName("appTitle")
        subtitle = QLabel("旧版实时引擎 · 仅保留用于兼容测试")
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)

        live_pill = QFrame()
        live_pill.setObjectName("livePill")
        live_layout = QHBoxLayout(live_pill)
        live_layout.setContentsMargins(9, 5, 11, 5)
        live_layout.setSpacing(6)
        self._live_dot = GlowDot(MUTED, size=10)
        self._live_label = QLabel("待机")
        self._live_label.setObjectName("liveText")
        set_tone(self._live_label, "gray")
        live_layout.addWidget(self._live_dot)
        live_layout.addWidget(self._live_label)
        header.addWidget(live_pill)

        settings_button = QPushButton("⚙")
        settings_button.setObjectName("iconButton")
        settings_button.setToolTip("设置：模型、视觉、思考与性能")
        settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_button.clicked.connect(self._on_open_settings)
        header.addWidget(settings_button)
        return header

    def _build_region_strip(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("regionStrip")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(11, 6, 9, 6)
        layout.setSpacing(7)

        self._region_dot = GlowDot(MUTED, size=9)
        self._region_label = QLabel(self._region_text())
        self._region_label.setObjectName("regionText")
        shortcut_hint = QLabel("Ctrl+Shift+S")
        shortcut_hint.setObjectName("shortcutHint")

        layout.addWidget(self._region_dot)
        layout.addWidget(self._region_label, 1)
        layout.addWidget(shortcut_hint)
        return strip

    def _build_left_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        chat_card = SectionCard("当前聊天", "OCR 文本可校正", CYAN)
        self._editor = OCREditor()
        self._editor.edited.connect(self._on_edited_applied)
        chat_card.add_widget(self._editor)
        column.addWidget(chat_card, 2)

        tools_card = SectionCard("画面与管道", "多模态 · 实时", TONE_COLORS["violet"])
        tools_card.setMinimumHeight(215)
        self._tools_tabs = QTabWidget()
        self._tools_tabs.setObjectName("toolTabs")
        self._tools_tabs.setDocumentMode(True)

        self._tools_tabs.addTab(self._build_image_tab(), "画面")
        self._pipeline = PipelinePanel()
        pipeline_tab = QWidget()
        pipeline_layout = QVBoxLayout(pipeline_tab)
        pipeline_layout.setContentsMargins(0, 0, 0, 0)
        pipeline_layout.setSpacing(0)
        pipeline_layout.addWidget(self._pipeline)
        self._tools_tabs.addTab(pipeline_tab, "管道")
        tools_card.add_widget(self._tools_tabs)
        column.addWidget(tools_card, 2)
        return column

    def _build_image_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._preview = ImagePreview()
        layout.addWidget(self._preview, 1)

        caption = QHBoxLayout()
        caption.setSpacing(6)
        self._vision_dot = GlowDot(GREEN, size=8)
        self._vision_caption = QLabel("")
        self._vision_caption.setObjectName("visionCaption")
        hint = QLabel("设置 → 分析")
        hint.setObjectName("visionHint")
        caption.addWidget(self._vision_dot)
        caption.addWidget(self._vision_caption, 1)
        caption.addWidget(hint)
        layout.addLayout(caption)
        return tab

    def _build_right_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        self._thinking = ThinkingPanel()
        column.addWidget(self._thinking, 0)

        self._analysis_card = SectionCard("AI 分析", "结构化字段", TONE_COLORS["indigo"])
        self._cards = AnalysisCards()
        self._analysis_card.add_widget(self._cards)
        column.addWidget(self._analysis_card, 4)

        replies_card = SectionCard("回复建议", "仅复制 · 不代发", GREEN)
        replies_card.setMinimumHeight(150)
        self._replies = ReplyList()
        self._replies.copy_requested.connect(lambda text: self._scheduler.notify("已复制到剪贴板"))
        replies_card.add_widget(self._replies)
        column.addWidget(replies_card, 2)
        return column

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(8)

        self._select_button = QPushButton("选择区域")
        self._select_button.setObjectName("primaryButton")
        self._select_button.setMinimumHeight(36)
        self._select_button.setIcon(crosshair_icon("#05070c", 16))
        self._select_button.setIconSize(QSize(16, 16))
        self._select_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_button.setToolTip("框选聊天窗口（Ctrl+Shift+S）")
        self._select_button.clicked.connect(self._on_select_region)

        self._pause_button = QPushButton("暂停监控")
        self._pause_button.setMinimumHeight(36)
        self._pause_button.setIcon(pause_icon("#c9d4e5", 16))
        self._pause_button.setIconSize(QSize(16, 16))
        self._pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pause_button.setToolTip("暂停或恢复对聊天区域的采样")
        self._pause_button.clicked.connect(self._on_toggle_pause)
        self._pause_button.setEnabled(False)

        clear_button = QPushButton("清空")
        clear_button.setObjectName("quietButton")
        clear_button.setMinimumHeight(36)
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.setToolTip("清空滚动上下文、当前分析与思考记录")
        clear_button.clicked.connect(self._on_clear)

        actions.addWidget(self._select_button, 2)
        actions.addWidget(self._pause_button, 2)
        actions.addWidget(clear_button, 1)
        return actions

    # ---- wiring ---------------------------------------------------------------

    def _connect_scheduler(self) -> None:
        s = self._scheduler
        s.state_changed.connect(self._on_state_changed)
        s.status_message.connect(self._on_status_message)
        s.region_changed.connect(self._on_region_changed)
        s.ocr_text_updated.connect(self._on_ocr_text)
        s.context_changed.connect(self._editor.set_context)
        s.ocr_activity.connect(self._status_bar.set_ocr_busy)
        s.llm_activity.connect(self._status_bar.set_llm_busy)
        s.engine_status_changed.connect(self._on_engine_status)
        s.analysis_started.connect(self._on_analysis_started)
        s.analysis_completed.connect(self._on_analysis_completed)
        s.analysis_failed.connect(self._on_analysis_failed)
        s.cleared.connect(self._on_cleared)
        s.metrics_updated.connect(self._on_metrics)
        s.metrics_updated.connect(self._status_bar.set_metrics)
        s.last_update.connect(self._status_bar.set_last_update)
        s.pipeline_log.connect(self._on_pipeline_log)
        s.stage_changed.connect(self._on_stage_changed)
        s.frame_preview.connect(self._on_frame_preview)
        s.thinking_started.connect(self._on_thinking_started)
        s.thinking_delta.connect(self._on_thinking_delta)

    def _apply_ui_settings(self) -> None:
        self._thinking.set_enabled(self._settings.thinking_enabled)
        self._thinking.set_auto_collapse(self._settings.thinking_auto_collapse)
        self._update_vision_caption()

    def _update_vision_caption(self) -> None:
        if self._settings.vision_enabled:
            self._vision_caption.setText("视觉分析开启 · 截图会随请求发送给模型")
            self._vision_dot.set_color(TONE_COLORS["amber"])
            set_tone(self._vision_caption, "warn")
        else:
            self._vision_caption.setText("画面仅本地预览 · 不随请求发送")
            self._vision_dot.set_color(GREEN)
            set_tone(self._vision_caption, "safe")

    def _refresh_from_scheduler(self) -> None:
        s = self._scheduler
        self._on_region_changed(s.region)
        self._pipeline.append_log(f"{time.strftime('%H:%M:%S')}  界面就绪 · 等待开始监控")
        self._pipeline.set_meta("latest-only · max 1 在途")
        if s.region is None:
            self._on_status_message("请选择聊天区域并开始监控")
        if not self._settings.is_llm_configured and not getattr(s, "_mock_llm", False):
            self._on_status_message("请在设置中配置 LLM API Key")

    # ---- scheduler slots ---------------------------------------------------------

    def _on_state_changed(self, text: str) -> None:
        self._status_bar.set_state(text)
        self._update_live_badge(text)
        monitoring = self._scheduler.is_monitoring
        paused = self._scheduler.state in (AppState.PAUSED, AppState.ERROR)
        self._pause_button.setText("恢复监控" if paused else "暂停监控")
        self._pause_button.setEnabled(monitoring or paused)
        if paused and self._thinking_active and text in ("暂停", "错误"):
            self._thinking_active = False
            self._thinking.abort("监控已暂停" if text == "暂停" else "监控错误")

    def _update_live_badge(self, text: str) -> None:
        tone = tone_for_state(text)
        self._live_label.setText(text)
        set_tone(self._live_label, tone)
        self._live_dot.set_color(TONE_COLORS[tone])
        self._live_dot.set_pulse(tone in ("cyan", "amber"))

    def _on_status_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    def _on_region_changed(self, region) -> None:
        self._region_label.setText(self._region_text())
        self._region_dot.set_color(CYAN if region is not None else MUTED)
        self._pause_button.setEnabled(region is not None)
        if region is None:
            self._preview.clear()

    def _on_ocr_text(self, text: str, raw: str) -> None:
        self._editor.set_ocr_text(text, raw)

    def _on_engine_status(self, text: str) -> None:
        if "加载" in text:
            self._status_bar.set_engine_loading()
        elif "失败" in text:
            self._status_bar.set_engine_failed()
        else:
            self._status_bar.set_ocr_busy(False)

    def _on_analysis_started(self) -> None:
        self._cards.set_updating(True)

    def _on_thinking_started(self) -> None:
        self._thinking_active = True
        self._thinking.begin()

    def _on_thinking_delta(self, delta: str) -> None:
        self._thinking.append(delta)

    def _on_analysis_completed(self, result) -> None:
        self._thinking_active = False
        self._cards.set_result(result)
        self._replies.set_replies(result.suggested_replies)
        self._thinking.finish(result.thinking)
        emotion = result.emotion
        if emotion.confidence is not None:
            hint = f"{emotion.label} · {round(emotion.confidence * 100)}%"
        else:
            hint = emotion.label or "结构化字段"
        if result.vision_used:
            hint += " · 视觉"
        self._analysis_card.set_hint(hint)

    def _on_analysis_failed(self, message: str) -> None:
        self._thinking_active = False
        self._cards.set_updating(False)
        self._cards.show_error(message)
        self._thinking.abort(message)
        self._analysis_card.set_hint("分析失败")

    def _on_cleared(self) -> None:
        self._thinking_active = False
        self._cards.clear_result()
        self._replies.clear_replies()
        self._editor.clear_all()
        self._thinking.reset()
        self._pipeline.reset_stages()
        self._analysis_card.set_hint("结构化字段")

    def _on_pipeline_log(self, line: str) -> None:
        self._pipeline.append_log(line)

    def _on_stage_changed(self, stage: str, state: str) -> None:
        self._pipeline.set_stage(stage, state)

    def _on_frame_preview(self, image) -> None:
        self._preview.set_frame(image)

    def _on_metrics(self, metrics: dict) -> None:
        generation = metrics.get("generation", 0)
        size = metrics.get("context_size", 0)
        self._pipeline.set_meta(f"gen #{generation} · ctx {size} · max 1 在途")

    # ---- actions ----------------------------------------------------------------

    def _on_select_region(self) -> None:
        self._was_monitoring_before_select = self._scheduler.is_monitoring
        self._scheduler.pause()
        self._selector = RegionSelector(self)
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.selection_cancelled.connect(self._on_region_cancelled)
        try:
            self._selector.start()
        except Exception as exc:
            logger.exception("failed to open region selector")
            self._on_status_message(f"无法打开区域选择器：{exc}")
            self._on_region_cancelled()

    def _on_region_selected(self, region) -> None:
        self._selector = None
        # spec: after confirming a selection the program starts monitoring
        self._scheduler.set_region_and_restart(region, resume_after=True)

    def _on_region_cancelled(self) -> None:
        self._selector = None
        if self._was_monitoring_before_select:
            self._scheduler.resume()

    def _on_toggle_pause(self) -> None:
        if self._scheduler.is_monitoring:
            self._scheduler.pause()
        else:
            self._scheduler.resume()

    def _on_clear(self) -> None:
        self._scheduler.clear_context()

    def _on_edited_applied(self, text: str) -> None:
        self._scheduler.set_user_override(text)
        self._scheduler.analyze_now(text, force=True)

    def _on_open_settings(self) -> None:
        from app.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self._settings, self)
        if dialog.exec():
            result = dialog.get_result()
            if result:
                self._settings = result["settings"]
                self._apply_on_top(result["always_on_top"])
                self._scheduler.apply_settings(self._settings)
                self._apply_ui_settings()
                self._pipeline.append_log(f"{time.strftime('%H:%M:%S')}  设置已保存")
                self._on_status_message("设置已保存")

    # ---- helpers ------------------------------------------------------------------

    def _region_text(self) -> str:
        region = self._scheduler.region
        if region is None:
            return "未选择监控区域"
        return (
            f"区域 ({region.x}, {region.y}) · "
            f"{region.width} × {region.height}"
        )

    def _fit_to_screen(self) -> None:
        """Keep the larger console inside the work area on small laptops."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(860, max(760, available.width() - 48))
        height = min(900, max(680, available.height() - 48))
        self.resize(width, height)

    def _apply_on_top(self, on_top: bool) -> None:
        flags = self.windowFlags()
        if on_top:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        if self.isVisible():
            self.show()

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self._selector is not None:
                self._selector.cancel()
            self._scheduler.shutdown()
        except Exception:
            pass
        self.closed.emit()
        super().closeEvent(event)

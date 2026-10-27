"""言外 · 对话解码器 — on-demand decoder window.

No continuous monitoring: the user pastes a long conversation and/or captures
one or more screenshots, then asks for a single decode.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.analysis.decoder import STAGES
from app.capture.region_selector import RegionSelector
from app.ui.floating_panel import AnalysisCards, ReplyList
from app.ui.panels import ImagePreview, PipelinePanel, ThinkingPanel
from app.ui.status_bar import AppStatusBar
from app.ui.styles import APP_QSS
from app.ui.widgets import (
    AMBER,
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
    set_tone,
    tone_for_state,
)

logger = logging.getLogger("yanwai.ui.decoder")


class DecoderWindow(QMainWindow):
    """言外 main window: long text + optional screenshots + one decode."""

    def __init__(self, controller, settings, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._settings = settings
        self._selector: RegionSelector | None = None
        self._capture_after_select = False

        self.setWindowTitle("言外 · 对话解码器")
        self.setMinimumSize(780, 680)
        self._fit_to_screen()
        self._apply_on_top(settings.always_on_top)
        self.setStyleSheet(APP_QSS)
        try:
            self.setWindowIcon(app_icon())
        except Exception:  # pragma: no cover
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

        self._read_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self._read_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._read_shortcut.activated.connect(self._on_read_clicked)

        self._decode_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._decode_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._decode_shortcut.activated.connect(self._on_analyze_clicked)

        self._connect_controller()
        self._apply_ui_settings()
        self._on_state_changed("待机")
        self._update_region_strip()
        self._pipeline.append_log(
                f"{time.strftime('%H:%M:%S')}  按需模式就绪 · 不会持续监控屏幕"
        )
        self._pipeline.append_log(
                f"{time.strftime('%H:%M:%S')}  粘贴长聊天记录，或点击「读取画面」框选一次"
        )

    # ---------------------------------------------------------------- building
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
        subtitle = QLabel("读懂言外之意 · 人与谜语人的对话解码器")
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)

        pill = QFrame()
        pill.setObjectName("livePill")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(9, 5, 11, 5)
        pill_layout.setSpacing(6)
        self._live_dot = GlowDot(MUTED, size=10)
        self._live_label = QLabel("待机")
        self._live_label.setObjectName("liveText")
        set_tone(self._live_label, "gray")
        pill_layout.addWidget(self._live_dot)
        pill_layout.addWidget(self._live_label)
        header.addWidget(pill)

        settings_button = QPushButton("⚙")
        settings_button.setObjectName("iconButton")
        settings_button.setToolTip("设置：模型、长文、视觉与思考")
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
        self._region_label = QLabel("尚未选区")
        self._region_label.setObjectName("regionText")
        self._region_dot.set_color(MUTED)
        hint = QLabel("Ctrl+Shift+S 读取 · Ctrl+Enter 解读")
        hint.setObjectName("shortcutHint")
        layout.addWidget(self._region_dot)
        layout.addWidget(self._region_label, 1)
        layout.addWidget(hint)
        return strip

    def _build_left_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        editor_card = SectionCard("对话内容", "粘贴 · 框选 · 可继续追加", CYAN)
        self._editor = QPlainTextEdit()
        self._editor.setObjectName("conversationEditor")
        self._editor.setPlaceholderText(
            "把完整聊天记录粘贴到这里（建议保留「对方：」「我：」这样的说话人标签）。\n\n"
            "也可以点击下方「读取画面」框选一次聊天窗口；聊天太长时，滚动后再次读取即可追加。"
        )
        self._editor.textChanged.connect(self._on_editor_changed)
        editor_card.add_widget(self._editor, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(1, 0, 1, 0)
        footer.setSpacing(7)
        self._char_label = QLabel("0 字")
        self._char_label.setObjectName("charCount")
        self._char_hint = QLabel("长文上限 30,000 字 · 超出会保留最近部分")
        self._char_hint.setObjectName("charHint")
        footer.addWidget(self._char_label)
        footer.addWidget(self._char_hint)
        footer.addStretch(1)
        clear_text = QPushButton("清空文本")
        clear_text.setObjectName("linkButton")
        clear_text.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_text.clicked.connect(self._on_clear_text)
        footer.addWidget(clear_text)
        editor_card.add_layout(footer)
        column.addWidget(editor_card, 3)

        tools_card = SectionCard("画面与管道", "按需 · 多模态", TONE_COLORS["violet"])
        tools_card.setMinimumHeight(225)
        self._tools_tabs = QTabWidget()
        self._tools_tabs.setObjectName("toolTabs")
        self._tools_tabs.setDocumentMode(True)
        self._tools_tabs.addTab(self._build_image_tab(), "画面")
        self._tools_tabs.addTab(self._build_pipeline_tab(), "管道")
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
        clear_images = QPushButton("清空画面")
        clear_images.setObjectName("linkButton")
        clear_images.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_images.clicked.connect(self._on_clear_images)
        caption.addWidget(self._vision_dot)
        caption.addWidget(self._vision_caption, 1)
        caption.addWidget(clear_images)
        layout.addLayout(caption)
        return tab

    def _build_pipeline_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._pipeline = PipelinePanel(STAGES)
        self._pipeline.set_meta("on-demand")
        layout.addWidget(self._pipeline)
        return tab

    def _build_right_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        self._thinking = ThinkingPanel()
        self._thinking.set_enabled(True)
        column.addWidget(self._thinking, 0)

        self._analysis_card = SectionCard("解读结果", "一次解读", TONE_COLORS["indigo"])
        self._cards = AnalysisCards()
        self._analysis_card.add_widget(self._cards)
        column.addWidget(self._analysis_card, 4)

        replies_card = SectionCard("可以这样回", "仅复制 · 不代发", GREEN)
        replies_card.setMinimumHeight(150)
        self._replies = ReplyList()
        self._replies.copy_requested.connect(
            lambda text: self._status_message(f"已复制：{text[:28]}{'…' if len(text) > 28 else ''}")
        )
        replies_card.add_widget(self._replies)
        column.addWidget(replies_card, 2)
        return column

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(8)

        self._reselect_button = QPushButton("重新框选")
        self._reselect_button.setMinimumHeight(36)
        self._reselect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reselect_button.setToolTip("重新选择要读取的聊天区域")
        self._reselect_button.clicked.connect(self._on_reselect_clicked)

        self._read_button = QPushButton("读取画面")
        self._read_button.setMinimumHeight(36)
        self._read_button.setIcon(crosshair_icon("#c9d4e5", 15))
        self._read_button.setIconSize(QSize(15, 15))
        self._read_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._read_button.setToolTip("框选一次并读取当前画面（Ctrl+Shift+S）；不会持续监控")
        self._read_button.clicked.connect(self._on_read_clicked)

        self._deep_check = QCheckBox("深度思考：关（较慢）")
        self._deep_check.setObjectName("deepCheck")
        self._deep_check.setStyleSheet(
            "QCheckBox::indicator { width: 0px; height: 0px; margin: 0px; }"
        )
        self._deep_check.setToolTip(
            "开启后使用推理模型的流式思考，通常需要 30–60 秒；默认快速解读。"
        )
        self._deep_check.toggled.connect(self._on_deep_toggled)

        self._analyze_button = QPushButton("解读这段对话")
        self._analyze_button.setObjectName("primaryButton")
        self._analyze_button.setMinimumHeight(38)
        self._analyze_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._analyze_button.setToolTip("把左侧全文和已读取的画面一起交给模型（Ctrl+Enter）")
        self._analyze_button.clicked.connect(self._on_analyze_clicked)

        actions.addWidget(self._reselect_button)
        actions.addWidget(self._read_button)
        actions.addWidget(self._deep_check)
        actions.addStretch(1)
        actions.addWidget(self._analyze_button, 2)
        return actions

    # ---------------------------------------------------------------- wiring
    def _connect_controller(self) -> None:
        c = self._controller
        c.state_changed.connect(self._on_state_changed)
        c.status_message.connect(self._status_message)
        c.engine_status_changed.connect(self._on_engine_status)
        c.ocr_activity.connect(self._status_bar.set_ocr_busy)
        c.llm_activity.connect(self._status_bar.set_llm_busy)
        c.busy_changed.connect(self._on_busy_changed)
        c.pipeline_log.connect(self._pipeline.append_log)
        c.stage_changed.connect(self._pipeline.set_stage)
        c.frame_preview.connect(self._preview.set_frame)
        c.images_changed.connect(self._on_images_changed)
        c.capture_completed.connect(self._on_capture_completed)
        c.analysis_started.connect(self._on_analysis_started)
        c.thinking_started.connect(self._thinking.begin)
        c.thinking_delta.connect(self._thinking.append)
        c.analysis_completed.connect(self._on_analysis_completed)
        c.analysis_failed.connect(self._on_analysis_failed)
        c.last_update.connect(self._status_bar.set_last_update)
        c.metrics_updated.connect(self._on_metrics)
        c.cleared.connect(self._on_cleared)

    def _apply_ui_settings(self) -> None:
        self._thinking.set_enabled(True)
        self._thinking.set_auto_collapse(self._settings.thinking_auto_collapse)
        self._deep_check.setChecked(bool(self._settings.thinking_enabled))
        self._deep_check.setToolTip(
            "开启后使用推理模型的流式思考，通常需要 30–60 秒；默认快速解读。"
        )
        self._char_hint.setText(
            f"长文上限 {self._settings.long_text_max_chars:,} 字 · 超出会保留最近部分"
        )
        self._update_vision_caption()
        self._on_editor_changed()

    # ---------------------------------------------------------------- actions
    def _on_editor_changed(self) -> None:
        text = self._editor.toPlainText()
        count = len(text)
        limit = max(1, int(self._settings.long_text_max_chars))
        self._char_label.setText(f"{count:,} 字")
        over = count > limit
        set_tone(self._char_label, "warn" if over else "muted")
        self._char_hint.setText(
            f"已超出 {count - limit:,} 字，解读时会保留最近部分"
            if over
            else f"长文上限 {limit:,} 字 · 超出会保留最近部分"
        )

    def _on_deep_toggled(self, enabled: bool) -> None:
        self._deep_check.setText(
            "深度思考：开（较慢）" if enabled else "深度思考：关（较慢）"
        )

    def _on_read_clicked(self) -> None:
        if self._controller.busy:
            self._status_message("当前正在处理，请稍等")
            return
        region = self._controller.region
        if region is None:
            self._start_region_select(capture_after=True)
        else:
            self._controller.capture(region)

    def _on_reselect_clicked(self) -> None:
        if self._controller.busy:
            self._status_message("当前正在处理，请稍等")
            return
        self._start_region_select(capture_after=False)

    def _start_region_select(self, *, capture_after: bool) -> None:
        self._capture_after_select = capture_after
        self._selector = RegionSelector(self)
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.selection_cancelled.connect(self._on_region_cancelled)
        try:
            self._selector.start()
        except Exception as exc:
            logger.exception("failed to open region selector")
            self._selector = None
            self._status_message(f"无法打开区域选择器：{exc}")

    def _on_region_selected(self, region) -> None:
        self._selector = None
        self._controller.set_region(region)
        self._update_region_strip()
        if self._capture_after_select:
            QTimer.singleShot(120, lambda: self._controller.capture(region))

    def _on_region_cancelled(self) -> None:
        self._selector = None

    def _on_analyze_clicked(self) -> None:
        if self._controller.busy:
            self._status_message("正在解读，请稍等")
            return
        self._controller.analyze(
            self._editor.toPlainText(),
            thinking=self._deep_check.isChecked(),
        )

    def _on_clear_text(self) -> None:
        self._editor.clear()

    def _on_clear_images(self) -> None:
        self._controller.clear_images()

    def _on_open_settings(self) -> None:
        from app.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self._settings, self)
        if dialog.exec():
            result = dialog.get_result()
            if result:
                self._settings = result["settings"]
                self._apply_on_top(result["always_on_top"])
                self._controller.set_settings(self._settings)
                self._apply_ui_settings()
                self._pipeline.append_log(
                    f"{time.strftime('%H:%M:%S')}  设置已保存"
                )
                self._status_message("设置已保存")

    # ---------------------------------------------------------------- signals
    def _on_state_changed(self, state: str) -> None:
        self._live_label.setText(state)
        tone = tone_for_state(state)
        set_tone(self._live_label, tone)
        self._live_dot.set_color(TONE_COLORS.get(tone, MUTED))
        self._live_dot.set_pulse(tone in ("cyan", "amber"))
        self._status_bar.set_state(state)
        if state == "解读中":
            self._analysis_card.set_hint("理解中…")
        elif state == "错误":
            self._analysis_card.set_hint("出现问题")

    def _on_busy_changed(self, busy: bool) -> None:
        self._read_button.setEnabled(not busy)
        self._reselect_button.setEnabled(not busy)
        self._analyze_button.setEnabled(not busy)
        self._analyze_button.setText("解读中…" if busy else "解读这段对话")

    def _on_engine_status(self, status: str) -> None:
        self._status_bar_engine(status)

    def _status_bar_engine(self, status: str) -> None:
        if "加载" in status:
            self._status_bar.set_engine_loading()
        elif "失败" in status:
            self._status_bar.set_engine_failed()
        else:
            self._status_bar.set_ocr_busy(False)

    def _on_images_changed(self, count: int) -> None:
        self._update_vision_caption()

    def _update_vision_caption(self) -> None:
        count = self._controller.image_count
        if not self._settings.vision_enabled:
            self._vision_caption.setText(
                f"画面仅本地预览 · 已附带 {count} 张不发送" if count else "画面仅本地预览 · 不发送"
            )
            self._vision_dot.set_color(GREEN)
            set_tone(self._vision_caption, "safe")
            return
        if count:
            self._vision_caption.setText(f"已附带 {count} 张画面 · 解读时会发送给模型")
            self._vision_dot.set_color(AMBER)
            set_tone(self._vision_caption, "warn")
        else:
            self._vision_caption.setText("尚未读取画面 · 可粘贴文本或框选一次")
            self._vision_dot.set_color(MUTED)
            set_tone(self._vision_caption, "muted")

    def _on_capture_completed(self, text: str) -> None:
        if not text.strip():
            return
        existing = self._editor.toPlainText().strip()
        if not existing:
            self._editor.setPlainText(text)
        else:
            old_lines = existing.splitlines()
            new_lines = text.splitlines()
            overlap = 0
            for n in range(min(len(old_lines), len(new_lines)), 0, -1):
                if old_lines[-n:] == new_lines[:n]:
                    overlap = n
                    break
            addition = new_lines[overlap:]
            if addition:
                self._editor.setPlainText(existing + "\n\n" + "\n".join(addition))
            else:
                self._status_message("画面内容已在文本中，没有重复追加")
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._editor.setTextCursor(cursor)
        self._editor.ensureCursorVisible()

    def _on_analysis_started(self) -> None:
        self._cards.set_updating(True)
        self._thinking.mark_pending(
            "解读中…",
            "深度思考" if self._deep_check.isChecked() else "快速模式",
        )

    def _on_analysis_completed(self, result) -> None:
        self._cards.set_result(result)
        self._replies.set_replies(result.suggested_replies)
        self._thinking.finish(result.thinking, deep=self._deep_check.isChecked())
        self._analysis_card.set_hint(
            f"{result.emotion.label} · {int(result.emotion.confidence * 100)}%"
            + (" · 视觉" if result.vision_used else "")
        )
        self._status_message("解读完成 · 回复只复制，不会自动发送")

    def _on_analysis_failed(self, message: str) -> None:
        self._cards.set_updating(False)
        self._cards.show_error(message)
        self._thinking.abort(message)
        self._analysis_card.set_hint("解读失败")

    def _on_cleared(self) -> None:
        self._editor.clear()
        self._cards.clear_result()
        self._replies.clear_replies()
        self._thinking.reset()
        self._preview.clear()
        self._pipeline.reset_stages()
        self._analysis_card.set_hint("一次解读")
        self._update_region_strip()
        self._update_vision_caption()
        self._status_bar.set_last_update(None)

    def _on_metrics(self, metrics: dict) -> None:
        self._status_bar.set_metrics(metrics)
        images = int(metrics.get("images", 0))
        chars = int(metrics.get("text_chars", 0))
        self._pipeline.set_meta(
            f"{images} 画面 · {chars:,} 字 · "
            f"{'深度' if metrics.get('thinking') else '快速'}"
        )
        self._update_vision_caption()

    def _status_message(self, message: str) -> None:
        self._status_bar.showMessage(message)
        self._live_label.setToolTip(message)

    def _update_region_strip(self) -> None:
        region = self._controller.region
        if region is None:
            self._region_label.setText("尚未选区 · 读取画面时会框选一次，不会持续监控")
            self._region_dot.set_color(MUTED)
        else:
            self._region_label.setText(
                f"区域 ({region.x}, {region.y}) · {region.width} × {region.height} · 按需读取"
            )
            self._region_dot.set_color(GREEN)

    # ---------------------------------------------------------------- lifecycle
    def _fit_to_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(900, 860)
            return
        available = screen.availableGeometry()
        width = min(900, max(780, available.width() - 48))
        height = min(860, max(680, available.height() - 48))
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
            self._controller.shutdown()
        except Exception:
            logger.exception("shutdown failed")
        event.accept()

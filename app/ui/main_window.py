"""Main window: floating always-on-top panel.

Layout (spec):
    header (title + region info)
    current chat (context / raw OCR / editable analysis text)
    AI analysis cards
    reply suggestions with copy buttons
    [选择区域] [暂停/恢复] [清空] [设置]
    status bar (state, OCR/LLM activity, last update)
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.analysis.scheduler import AppState
from app.capture.region_selector import RegionSelector
from app.ui.floating_panel import AnalysisCards, ReplyList
from app.ui.ocr_editor import OCREditor
from app.ui.status_bar import AppStatusBar
from app.ui.styles import APP_QSS

logger = logging.getLogger("ocr_chat.ui.main")


class MainWindow(QMainWindow):
    closed = Signal()

    def __init__(self, scheduler, settings, parent=None) -> None:
        super().__init__(parent)
        self._scheduler = scheduler
        self._settings = settings
        self._selector: RegionSelector | None = None
        self._was_monitoring_before_select = False

        self.setWindowTitle("OCR Chat Assistant — 聊天语义助手")
        self.resize(430, 680)
        self._apply_on_top(settings.always_on_top)
        self.setStyleSheet(APP_QSS)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # ---- header ---------------------------------------------------------
        header = QHBoxLayout()
        self._region_label = QLabel(self._region_text())
        self._region_label.setObjectName("hintLabel")
        header.addWidget(self._region_label)
        header.addStretch(1)
        settings_button = QPushButton("⚙ 设置")
        settings_button.clicked.connect(self._on_open_settings)
        header.addWidget(settings_button)
        root.addLayout(header)

        # ---- current chat / OCR editor ---------------------------------------
        chat_box = QGroupBox("当前聊天")
        chat_layout = QVBoxLayout(chat_box)
        self._editor = OCREditor()
        self._editor.edited.connect(self._on_edited_applied)
        chat_layout.addWidget(self._editor)
        root.addWidget(chat_box, 2)

        # ---- analysis ---------------------------------------------------------
        analysis_box = QGroupBox("AI 分析")
        analysis_layout = QVBoxLayout(analysis_box)
        self._cards = AnalysisCards()
        analysis_layout.addWidget(self._cards)
        root.addWidget(analysis_box, 3)

        # ---- replies ----------------------------------------------------------
        replies_box = QGroupBox("回复建议")
        replies_layout = QVBoxLayout(replies_box)
        self._replies = ReplyList()
        self._replies.copy_requested.connect(lambda text: self._scheduler.notify("已复制到剪贴板"))
        replies_layout.addWidget(self._replies)
        root.addWidget(replies_box, 1)

        # ---- buttons -----------------------------------------------------------
        buttons = QHBoxLayout()
        self._select_button = QPushButton("选择区域")
        self._select_button.clicked.connect(self._on_select_region)
        self._pause_button = QPushButton("暂停监控")
        self._pause_button.clicked.connect(self._on_toggle_pause)
        self._pause_button.setEnabled(False)
        clear_button = QPushButton("清空上下文")
        clear_button.clicked.connect(self._on_clear)
        settings_button2 = QPushButton("设置")
        settings_button2.clicked.connect(self._on_open_settings)
        buttons.addWidget(self._select_button)
        buttons.addWidget(self._pause_button)
        buttons.addWidget(clear_button)
        buttons.addWidget(settings_button2)
        root.addLayout(buttons)

        # ---- status bar --------------------------------------------------------
        self._status_bar = AppStatusBar()
        self.setStatusBar(self._status_bar)

        # ---- shortcuts ----------------------------------------------------------
        self._shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self._shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut.activated.connect(self._on_select_region)

        self._connect_scheduler()
        self._refresh_from_scheduler()

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
        s.metrics_updated.connect(self._status_bar.set_metrics)
        s.last_update.connect(self._status_bar.set_last_update)

    def _refresh_from_scheduler(self) -> None:
        s = self._scheduler
        self._on_region_changed(s.region)
        if s.region is None:
            self._on_status_message("请选择聊天区域并开始监控")
        if not self._settings.is_llm_configured and not getattr(s, "_mock_llm", False):
            self._on_status_message("请在设置中配置 LLM API Key")

    # ---- scheduler slots ---------------------------------------------------------

    def _on_state_changed(self, text: str) -> None:
        self._status_bar.set_state(text)
        monitoring = self._scheduler.is_monitoring
        paused = self._scheduler.state in (AppState.PAUSED, AppState.ERROR)
        self._pause_button.setText("恢复监控" if paused else "暂停监控")
        self._pause_button.setEnabled(monitoring or paused)

    def _on_status_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    def _on_region_changed(self, region) -> None:
        self._region_label.setText(self._region_text())
        self._pause_button.setEnabled(region is not None)

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

    def _on_analysis_completed(self, result) -> None:
        self._cards.set_result(result)
        self._replies.set_replies(result.suggested_replies)

    def _on_analysis_failed(self, message: str) -> None:
        self._cards.set_updating(False)
        self._cards.show_error(message)

    def _on_cleared(self) -> None:
        self._cards.clear_result()
        self._replies.clear_replies()
        self._editor.clear_all()

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
                self._on_status_message("设置已保存")

    # ---- helpers ------------------------------------------------------------------

    def _region_text(self) -> str:
        region = self._scheduler.region
        if region is None:
            return "监控区域：未选择"
        return (
            f"监控区域：({region.x}, {region.y}) "
            f"{region.width}×{region.height}"
        )

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

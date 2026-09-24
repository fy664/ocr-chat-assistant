"""OCR text editing (spec: user may fix, delete, add, copy OCR text).

Tabs:
  - 当前聊天 : rolling context view (read-only, with speaker hints)
  - OCR 原文 : latest raw OCR output (read-only, copyable)
  - 分析文本 : editable text fed to analysis (edit -> 应用并分析)
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("ocr_chat.ui.editor")


class OCREditor(QWidget):
    edited = Signal(str)          # user clicked 应用并分析 (edited text)
    override_active_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._override_active = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._tabs = QTabWidget()

        # tab 1: rolling context
        self._context_view = QPlainTextEdit()
        self._context_view.setReadOnly(True)
        self._context_view.setPlaceholderText("当前可见聊天上下文（开始监控后自动更新）")
        self._tabs.addTab(self._context_view, "当前聊天")

        # tab 2: raw OCR
        self._raw_view = QPlainTextEdit()
        self._raw_view.setReadOnly(True)
        self._raw_view.setPlaceholderText("OCR 原文")
        self._tabs.addTab(self._raw_view, "OCR 原文")

        # tab 3: editable analysis text
        edit_container = QWidget()
        edit_layout = QVBoxLayout(edit_container)
        edit_layout.setContentsMargins(4, 4, 4, 4)
        edit_layout.setSpacing(4)
        self._edit_view = QPlainTextEdit()
        self._edit_view.setPlaceholderText("用于分析的文本（可直接修改，修改后点击「应用并分析」）")
        edit_layout.addWidget(self._edit_view, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self._edited_badge = QLabel("")
        self._edited_badge.setObjectName("errorLabel")
        buttons.addWidget(self._edited_badge)
        buttons.addStretch(1)
        restore_button = QPushButton("恢复 OCR 文本")
        restore_button.clicked.connect(self._on_restore)
        copy_button = QPushButton("复制")
        copy_button.clicked.connect(self._on_copy)
        apply_button = QPushButton("应用并分析")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self._on_apply)
        buttons.addWidget(restore_button)
        buttons.addWidget(copy_button)
        buttons.addWidget(apply_button)
        edit_layout.addLayout(buttons)
        self._tabs.addTab(edit_container, "分析文本")

        root.addWidget(self._tabs)
        self._last_ocr_text = ""

    # ---- inputs from scheduler --------------------------------------------

    def set_ocr_text(self, normalized_text: str, raw_text: str) -> None:
        """New OCR snapshot: refresh views and drop any pending user edit."""
        self._last_ocr_text = normalized_text
        self._raw_view.setPlainText(raw_text if raw_text else normalized_text)
        if not self._override_active:
            self._edit_view.setPlainText(normalized_text)
        self._context_view.setPlainText(normalized_text)
        self._set_override_active(False)

    def set_context(self, context) -> None:
        lines = context.to_display_lines()
        text = "\n".join(lines)
        if text != self._context_view.toPlainText():
            self._context_view.setPlainText(text)

    def set_override_text(self, text: str) -> None:
        """Called when the scheduler applies a user edit."""
        self._edit_view.setPlainText(text)
        self._set_override_active(True)

    def clear_all(self) -> None:
        self._last_ocr_text = ""
        self._raw_view.clear()
        self._edit_view.clear()
        self._context_view.clear()
        self._set_override_active(False)

    # ---- internals -----------------------------------------------------------

    def _set_override_active(self, active: bool) -> None:
        if active == self._override_active:
            return
        self._override_active = active
        if active:
            self._edited_badge.setText("已编辑 — 分析将使用编辑后文本")
            self._tabs.setTabText(2, "分析文本 *")
        else:
            self._edited_badge.setText("")
            self._tabs.setTabText(2, "分析文本")
        self.override_active_changed.emit(active)

    def _on_apply(self) -> None:
        text = self._edit_view.toPlainText().strip()
        if not text:
            return
        self._set_override_active(True)
        self.edited.emit(text)

    def _on_restore(self) -> None:
        self._edit_view.setPlainText(self._last_ocr_text)
        self._set_override_active(False)

    def _on_copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._edit_view.toPlainText())

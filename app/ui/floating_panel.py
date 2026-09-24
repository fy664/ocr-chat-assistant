"""Analysis display widgets: result cards + reply suggestions.

Update policy: old results stay visible until a new result is ready
(no blank flash); a small "正在更新分析…" indicator shows while a new
analysis is in flight; failures keep the old result and show the error.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models.schemas import AnalysisResult

logger = logging.getLogger("ocr_chat.ui")


def _card(title: str, body_text: str = "—") -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("cardFrame")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(4)
    title_label = QLabel(title)
    title_label.setObjectName("cardTitle")
    body = QLabel(body_text)
    body.setObjectName("cardBody")
    body.setWordWrap(True)
    body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(title_label)
    layout.addWidget(body)
    return frame, body


class AnalysisCards(QWidget):
    """Result cards. Cards are rebuilt per result (fresh widgets) so that
    deferred deletion of the previous set never conflicts with re-adding."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._result: AnalysisResult | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._updating = QLabel("正在更新分析…")
        self._updating.setObjectName("hintLabel")
        self._updating.hide()

        self._error = QLabel("")
        self._error.setObjectName("errorLabel")
        self._error.setWordWrap(True)
        self._error.hide()

        self._empty = QLabel("尚未分析。选择聊天区域并开始监控后，检测到新消息将自动分析。")
        self._empty.setObjectName("hintLabel")
        self._empty.setWordWrap(True)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._cards_layout = QVBoxLayout(self._inner)
        self._cards_layout.setContentsMargins(0, 0, 4, 0)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addWidget(self._empty)
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(self._inner)
        self._scroll.hide()

        root.addWidget(self._updating)
        root.addWidget(self._error)
        root.addWidget(self._scroll)

    @property
    def current_result(self) -> AnalysisResult | None:
        return self._result

    def set_updating(self, updating: bool) -> None:
        self._updating.setVisible(updating)

    def show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.show()
        QTimer.singleShot(8000, self._hide_error)

    def _hide_error(self) -> None:
        self._error.hide()

    def set_result(self, result: AnalysisResult) -> None:
        """Atomic replace of the whole card block (stable layout, no jumping)."""
        self._result = result
        self._error.hide()
        self._updating.hide()

        self._remove_all_cards()
        for frame in self._build_cards(result):
            self._cards_layout.addWidget(frame)
        self._cards_layout.addStretch(1)
        self._scroll.show()
        self._empty.hide()

    def clear_result(self) -> None:
        self._result = None
        self._error.hide()
        self._updating.hide()
        self._remove_all_cards()
        self._cards_layout.addWidget(self._empty)
        self._cards_layout.addStretch(1)
        self._scroll.hide()
        self._empty.show()

    def _remove_all_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._empty:
                widget.deleteLater()

    def _build_cards(self, result: AnalysisResult) -> list[QFrame]:
        cards: list[QFrame] = []

        cards.append(_card("当前理解", result.surface_meaning or "—")[0])

        intent_text = "\n".join(f"· {i}" for i in result.possible_intent) or "—"
        cards.append(_card("可能意图", intent_text)[0])

        emotion = result.emotion
        if emotion.confidence is not None:
            emotion_text = f"{emotion.label}（置信度 {emotion.confidence:.0%}）"
        else:
            emotion_text = emotion.label
        if emotion.evidence:
            emotion_text += f"\n依据：{emotion.evidence}"
        cards.append(_card("情绪", emotion_text)[0])

        needs_text = "\n".join(f"· {n}" for n in result.potential_needs) or "—"
        cards.append(_card("潜在诉求", needs_text)[0])

        cards.append(_card("建议策略", result.reply_strategy or "—")[0])
        cards.append(_card("不确定性", result.uncertainty or "—")[0])
        return cards


class ReplyList(QWidget):
    """2-3 suggested replies, each with its own copy button.

    V1 copies to the clipboard only - never auto-pastes, never auto-sends.
    """

    copy_requested = Signal(str)  # text copied (for status feedback)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._empty = QLabel("暂无回复建议")
        self._empty.setObjectName("hintLabel")
        self._layout.addWidget(self._empty)

    def set_replies(self, replies) -> None:
        self._clear_rows()

        if not replies:
            self._layout.addWidget(self._empty)
            return

        for reply in replies:
            row = QFrame()
            row.setObjectName("cardFrame")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 6, 10, 6)
            row_layout.setSpacing(8)

            style_label = QLabel(reply.style)
            style_label.setObjectName("replyStyle")
            style_label.setFixedWidth(48)
            style_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            text_label = QLabel(reply.text)
            text_label.setWordWrap(True)
            text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            copy_button = QPushButton("复制")
            copy_button.setFixedWidth(56)
            copy_button.clicked.connect(
                lambda checked=False, text=reply.text, button=copy_button: self._copy(text, button)
            )

            row_layout.addWidget(style_label)
            row_layout.addWidget(text_label, 1)
            row_layout.addWidget(copy_button)
            self._layout.addWidget(row)

    def clear_replies(self) -> None:
        self._clear_rows()
        self._layout.addWidget(self._empty)

    def _clear_rows(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._empty:
                widget.deleteLater()

    def _copy(self, text: str, button: QPushButton) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self.copy_requested.emit(text)
        button.setText("已复制")
        QTimer.singleShot(1200, lambda: button.setText("复制"))

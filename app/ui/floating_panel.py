"""Analysis display widgets: glass result cards + reply suggestions.

Update policy (unchanged): old results stay visible until a new result is
ready; a compact updating pill with an animated gradient bar shows while a
request is in flight; failures keep the old result and surface an error pill.
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
from app.ui.widgets import (
    TONE_COLORS,
    GlowDot,
    PulseBar,
    RingMeter,
)

logger = logging.getLogger("ocr_chat.ui")

CARD_TONES = {
    "当前理解": "cyan",
    "证据": "cyan",
    "可能意图": "indigo",
    "情绪": "amber",
    "潜在诉求": "violet",
    "替代解释": "muted",
    "建议策略": "green",
    "不确定性": "muted",
}


def _label(text: str, object_name: str, *, wrap: bool = True, selectable: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    label.setWordWrap(wrap)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _card(title: str, tone: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("analysisCard")
    frame.setProperty("tone", tone)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 8, 10, 9)
    layout.setSpacing(5)

    header = QHBoxLayout()
    header.setSpacing(6)
    header.addWidget(GlowDot(TONE_COLORS.get(tone, TONE_COLORS["muted"]), size=9))
    title_label = QLabel(title)
    title_label.setObjectName("cardTitle")
    header.addWidget(title_label)
    header.addStretch(1)
    layout.addLayout(header)
    return frame, layout


class AnalysisCards(QWidget):
    """Result cards. Cards are rebuilt per result so replacing the block is atomic."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._result: AnalysisResult | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # --- updating indicator ------------------------------------------------
        self._updating = QWidget()
        updating_layout = QVBoxLayout(self._updating)
        updating_layout.setContentsMargins(0, 0, 0, 0)
        updating_layout.setSpacing(5)

        pill = QFrame()
        pill.setObjectName("updatingPill")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(8, 4, 9, 4)
        pill_layout.setSpacing(7)
        self._updating_dot = GlowDot(TONE_COLORS["cyan"], size=10, pulse=True)
        pill_layout.addWidget(self._updating_dot)
        self._updating_text = QLabel("正在更新分析…")
        self._updating_text.setObjectName("updatingText")
        pill_layout.addWidget(self._updating_text)
        pill_layout.addStretch(1)
        updating_layout.addWidget(pill)

        self._pulse = PulseBar()
        updating_layout.addWidget(self._pulse)
        self._updating.hide()

        # --- error -------------------------------------------------------------
        self._error = QLabel("")
        self._error.setObjectName("errorLabel")
        self._error.setWordWrap(True)
        self._error.hide()

        # --- empty state -------------------------------------------------------
        self._empty = QLabel(
            '<div style="text-align:center;">'
            '<span style="font-size:14px; color:#c8d5e8;"><b>等待一次解读</b></span>'
            "<br><br>"
            '<span style="color:#8b98ae;">粘贴一段对话，或读取一次画面，<br>'
            "然后点击「解读这段对话」。</span>"
            "</div>"
        )
        self._empty.setObjectName("emptyState")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # --- scrollable cards --------------------------------------------------
        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.viewport().setStyleSheet("background: transparent;")

        self._inner = QWidget()
        self._inner.setObjectName("cardsInner")
        self._cards_layout = QVBoxLayout(self._inner)
        self._cards_layout.setContentsMargins(0, 0, 3, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(self._inner)
        self._scroll.hide()

        root.addWidget(self._updating)
        root.addWidget(self._error)
        root.addWidget(self._empty, 1)
        root.addWidget(self._scroll, 1)

    @property
    def current_result(self) -> AnalysisResult | None:
        return self._result

    def set_updating(self, updating: bool) -> None:
        self._updating.setVisible(updating)
        self._pulse.set_active(updating)
        if updating:
            self._error.hide()

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
        self._updating.setVisible(False)
        self._pulse.set_active(False)

        self._remove_all_cards()
        for frame in self._build_cards(result):
            self._cards_layout.addWidget(frame)
        self._cards_layout.addStretch(1)
        self._scroll.show()
        self._empty.hide()
        self._scroll.verticalScrollBar().setValue(0)

    def clear_result(self) -> None:
        self._result = None
        self._error.hide()
        self._updating.setVisible(False)
        self._pulse.set_active(False)
        self._remove_all_cards()
        self._cards_layout.addStretch(1)
        self._scroll.hide()
        self._empty.show()

    def _remove_all_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    # ---- card builders -------------------------------------------------------

    def _build_cards(self, result: AnalysisResult) -> list[QFrame]:
        cards: list[QFrame] = []

        card, layout = _card("当前理解", CARD_TONES["当前理解"])
        layout.addWidget(_label(result.surface_meaning or "—", "cardBody"))
        cards.append(card)

        if result.evidence:
            card, layout = _card("证据", CARD_TONES["证据"])
            layout.addWidget(self._chip_block(result.evidence))
            cards.append(card)

        card, layout = _card("可能意图", CARD_TONES["可能意图"])
        layout.addWidget(self._chip_block(result.possible_intent))
        cards.append(card)

        card, layout = _card("情绪", CARD_TONES["情绪"])
        layout.addLayout(self._emotion_row(result))
        cards.append(card)

        card, layout = _card("潜在诉求", CARD_TONES["潜在诉求"])
        layout.addWidget(self._chip_block(result.potential_needs))
        cards.append(card)

        if result.alternatives:
            card, layout = _card("替代解释", CARD_TONES["替代解释"])
            layout.addWidget(self._chip_block(result.alternatives))
            cards.append(card)

        card, layout = _card("建议策略", CARD_TONES["建议策略"])
        layout.addWidget(_label(result.reply_strategy or "—", "cardBody"))
        cards.append(card)

        card, layout = _card("不确定性", CARD_TONES["不确定性"])
        layout.addWidget(_label(result.uncertainty or "—", "mutedText"))
        cards.append(card)

        return cards

    @staticmethod
    def _chip_block(items: list[str]) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        if not items:
            layout.addWidget(_label("—", "mutedText"))
            return box
        for item in items:
            layout.addWidget(_label(f"·  {item}", "chipItem", wrap=True))
        return box

    @staticmethod
    def _emotion_row(result: AnalysisResult) -> QHBoxLayout:
        emotion = result.emotion
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(11)

        ring = RingMeter(emotion.confidence, size=48)
        row.addWidget(ring, 0, Qt.AlignmentFlag.AlignVCenter)

        meta = QVBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(2)
        meta.addWidget(_label(emotion.label or "—", "emotionLabel"))
        if emotion.evidence:
            meta.addWidget(_label(f"依据 · {emotion.evidence}", "mutedText"))
        meta.addStretch(1)
        row.addLayout(meta, 1)
        return row


class ReplyList(QWidget):
    """2–3 suggested replies, each with its own copy button.

    V1 copies to the clipboard only — never auto-pastes, never auto-sends.
    """

    copy_requested = Signal(str)  # text copied (for status feedback)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._empty = QLabel("暂无回复建议")
        self._empty.setObjectName("hintLabel")
        self._layout.addWidget(self._empty)

    def set_replies(self, replies) -> None:
        self._clear_rows()

        if not replies:
            self._empty.show()
            self._layout.addWidget(self._empty)
            return

        for reply in replies:
            row = QFrame()
            row.setObjectName("replyRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(9, 6, 9, 6)
            row_layout.setSpacing(8)

            style_label = QLabel(reply.style)
            style_label.setObjectName("replyStyle")
            style_label.setFixedWidth(40)
            style_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            text_column = QVBoxLayout()
            text_column.setContentsMargins(0, 0, 0, 0)
            text_column.setSpacing(2)
            text_label = QLabel(reply.text)
            text_label.setObjectName("replyText")
            text_label.setWordWrap(True)
            text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text_column.addWidget(text_label)
            why = getattr(reply, "why", "") or ""
            if why:
                why_label = QLabel(why)
                why_label.setObjectName("replyWhy")
                why_label.setWordWrap(True)
                text_column.addWidget(why_label)

            copy_button = QPushButton("复制")
            copy_button.setObjectName("copyButton")
            copy_button.setFixedWidth(48)
            copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_button.clicked.connect(
                lambda checked=False, text=reply.text, button=copy_button: self._copy(text, button)
            )

            row_layout.addWidget(style_label, 0, Qt.AlignmentFlag.AlignVCenter)
            row_layout.addLayout(text_column, 1)
            row_layout.addWidget(copy_button, 0, Qt.AlignmentFlag.AlignVCenter)
            self._layout.addWidget(row)

    def clear_replies(self) -> None:
        self._clear_rows()
        self._empty.show()
        self._layout.addWidget(self._empty)

    def _clear_rows(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is self._empty:
                widget.hide()
                continue
            if widget is not None:
                widget.deleteLater()

    def _copy(self, text: str, button: QPushButton) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self.copy_requested.emit(text)
        button.setText("已复制")
        button.setProperty("copied", True)
        button.style().unpolish(button)
        button.style().polish(button)
        QTimer.singleShot(1200, lambda: self._reset_button(button))

    @staticmethod
    def _reset_button(button: QPushButton) -> None:
        button.setText("复制")
        button.setProperty("copied", False)
        button.style().unpolish(button)
        button.style().polish(button)

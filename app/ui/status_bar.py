"""Status bar: state dot, transient message, OCR/LLM activity and update clock."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QStatusBar,
    QWidget,
)

from app.utils.time import format_clock
from app.ui.widgets import (
    GREEN,
    MUTED,
    RED,
    TONE_COLORS,
    ElidedLabel,
    GlowDot,
    set_tone,
    tone_for_state,
)

AMBER = TONE_COLORS["amber"]


def _chip(dot: GlowDot, label: QLabel) -> QFrame:
    chip = QFrame()
    chip.setObjectName("statusChip")
    layout = QHBoxLayout(chip)
    layout.setContentsMargins(6, 2, 7, 2)
    layout.setSpacing(5)
    layout.addWidget(dot)
    layout.addWidget(label)
    chip.setFixedHeight(20)
    return chip


class AppStatusBar(QStatusBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self.setFixedHeight(34)
        self._metrics: dict = {}

        content = QWidget()
        content.setObjectName("statusContent")
        layout = QHBoxLayout(content)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(7)

        self._state_dot = GlowDot(MUTED, size=9)
        self._state_label = QLabel("未开始")
        self._state_label.setObjectName("statusState")
        set_tone(self._state_label, "gray")
        layout.addWidget(self._state_dot)
        layout.addWidget(self._state_label)

        separator = QFrame()
        separator.setFixedSize(1, 11)
        separator.setStyleSheet("background: rgba(255,255,255,0.09); border: none;")
        layout.addWidget(separator)

        self._message_label = ElidedLabel("", "#9fe8f5")
        self._message_label.setObjectName("statusMessage")
        self._message_label.hide()
        layout.addWidget(self._message_label, 1)

        self._ocr_dot = GlowDot(MUTED, size=8)
        self._ocr_label = QLabel("OCR 就绪")
        self._ocr_label.setObjectName("statusChipText")
        set_tone(self._ocr_label, "ok")
        layout.addWidget(_chip(self._ocr_dot, self._ocr_label))

        self._llm_dot = GlowDot(MUTED, size=8)
        self._llm_label = QLabel("LLM 就绪")
        self._llm_label.setObjectName("statusChipText")
        set_tone(self._llm_label, "ok")
        layout.addWidget(_chip(self._llm_dot, self._llm_label))

        self._update_label = QLabel("--:--:--")
        self._update_label.setObjectName("statusClock")
        self._update_label.setToolTip("最近一次分析更新时间")
        layout.addWidget(self._update_label)

        self.addPermanentWidget(content, 1)

        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self.clearMessage)

    # ---- state ---------------------------------------------------------------

    def set_state(self, text: str) -> None:
        self._state_label.setText(text)
        tone = tone_for_state(text)
        set_tone(self._state_label, tone)
        self._state_dot.set_color(TONE_COLORS[tone])
        self._state_dot.set_pulse(tone in ("cyan", "amber"))

    def set_ocr_busy(self, busy: bool) -> None:
        self._ocr_label.setText("OCR 忙碌" if busy else "OCR 就绪")
        set_tone(self._ocr_label, "busy" if busy else "ok")
        self._ocr_dot.set_color(AMBER if busy else GREEN)
        self._ocr_dot.set_pulse(busy)

    def set_llm_busy(self, busy: bool) -> None:
        self._llm_label.setText("LLM 忙碌" if busy else "LLM 就绪")
        set_tone(self._llm_label, "busy" if busy else "ok")
        self._llm_dot.set_color(AMBER if busy else GREEN)
        self._llm_dot.set_pulse(busy)

    def set_engine_loading(self) -> None:
        self._ocr_label.setText("OCR 加载中…")
        set_tone(self._ocr_label, "busy")
        self._ocr_dot.set_color(AMBER)
        self._ocr_dot.set_pulse(True)

    def set_engine_failed(self) -> None:
        self._ocr_label.setText("OCR 失败")
        set_tone(self._ocr_label, "error")
        self._ocr_dot.set_color(RED)
        self._ocr_dot.set_pulse(False)

    # ---- clock / transient message --------------------------------------------

    def set_last_update(self, ts: float | None) -> None:
        clock = format_clock(ts)
        self._update_label.setText(clock)
        self._update_label.setToolTip(f"最近一次分析更新时间：{clock}")

    def showMessage(self, message: str, timeout: int = 0) -> None:  # noqa: N802
        if not message:
            self.clearMessage()
            return
        self._message_label.setText(message)
        self._message_label.setToolTip(message)
        self._message_label.show()
        self._message_timer.start(timeout if timeout and timeout > 0 else 6000)

    def clearMessage(self) -> None:  # noqa: N802
        self._message_timer.stop()
        self._message_label.clear()
        self._message_label.setToolTip("")
        self._message_label.hide()

    def set_metrics(self, metrics: dict) -> None:
        self._metrics = metrics
        if not metrics:
            return
        if "images" in metrics:
            parts = [
                f"状态: {metrics.get('state', '')}",
                f"附带画面: {metrics.get('images', 0)} 张",
                f"对话文本: {metrics.get('text_chars', 0)} 字",
                f"模式: {'深度' if metrics.get('thinking') else '快速'}",
            ]
        else:
            parts = [
                f"状态: {metrics.get('state', '')}",
                f"上下文: {metrics.get('context_size', 0)} 条 / {metrics.get('context_chars', 0)} 字符",
                f"分析代数: {metrics.get('generation', 0)}",
            ]
        if metrics.get("ocr_latency_s") is not None:
            parts.append(f"OCR 耗时: {metrics['ocr_latency_s'] * 1000:.0f} ms")
        if metrics.get("llm_latency_s") is not None:
            parts.append(f"LLM 耗时: {metrics['llm_latency_s'] * 1000:.0f} ms")
        self.setToolTip("\n".join(parts))

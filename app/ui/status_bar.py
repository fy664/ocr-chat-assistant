"""Status bar: app state, OCR/LLM activity, last update time + metrics tooltip."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QStatusBar

from app.utils.time import format_clock


class AppStatusBar(QStatusBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state_label = QLabel("未开始")
        self._ocr_label = QLabel("OCR: --")
        self._llm_label = QLabel("LLM: --")
        self._update_label = QLabel("更新: --:--:--")
        self._metrics: dict = {}

        self.addWidget(self._state_label)
        self.addPermanentWidget(self._update_label)
        self.addPermanentWidget(self._ocr_label)
        self.addPermanentWidget(self._llm_label)

    def set_state(self, text: str) -> None:
        self._state_label.setText(text)

    def set_ocr_busy(self, busy: bool) -> None:
        self._ocr_label.setText("OCR: 忙碌" if busy else "OCR: 就绪")

    def set_llm_busy(self, busy: bool) -> None:
        self._llm_label.setText("LLM: 忙碌" if busy else "LLM: 就绪")

    def set_engine_loading(self) -> None:
        self._ocr_label.setText("OCR: 加载中…")

    def set_engine_failed(self) -> None:
        self._ocr_label.setText("OCR: 失败")

    def set_last_update(self, ts: float | None) -> None:
        self._update_label.setText(f"更新: {format_clock(ts)}")

    def set_metrics(self, metrics: dict) -> None:
        self._metrics = metrics
        if not metrics:
            return
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

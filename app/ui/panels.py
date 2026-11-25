"""Composite panels for the v2 desktop UI.

- ThinkingPanel : DeepSeek-style collapsible reasoning trail
- StageStepper  : 5-stage realtime pipeline indicator
- PipelineLog   : timestamped pipeline timeline
- ImagePreview  : live collection view and single-frame preview
"""
from __future__ import annotations

import time

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets import (
    AMBER,
    CYAN,
    GREEN,
    MUTED,
    RED,
    GlowDot,
    set_tone,
)

STAGE_DEFS = (
    ("ocr", "OCR 采样"),
    ("diff", "变化检测"),
    ("debounce", "稳定防抖"),
    ("llm", "语义分析"),
    ("ui", "更新面板"),
)
_STAGE_COLORS = {
    "idle": QColor("#5d6a80"),
    "active": CYAN,
    "done": GREEN,
    "error": RED,
}


class ThinkingPanel(QFrame):
    """Collapsible reasoning trail with a DeepSeek-like summary header."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("thinkingPanel")
        self._enabled = True
        self._auto_collapse = True
        self._expanded = False
        self._started: float | None = None
        self._buffer = ""
        self._streamed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(7)
        self._dot = GlowDot(MUTED, size=10)
        self._toggle = QToolButton()
        self._toggle.setObjectName("thinkingToggle")
        self._toggle.setText("深度思考")
        self._toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(self._on_toggle_clicked)
        self._status = QLabel("等待分析")
        self._status.setObjectName("thinkingStatus")
        header.addWidget(self._dot)
        header.addWidget(self._toggle)
        header.addWidget(self._status)
        header.addStretch(1)
        hint = QLabel("点击展开")
        hint.setObjectName("thinkingHint")
        self._hint = hint
        header.addWidget(hint)
        root.addLayout(header)

        self._body = QPlainTextEdit()
        self._body.setObjectName("thinkingView")
        self._body.setReadOnly(True)
        self._body.setPlaceholderText("模型的思考路径会显示在这里")
        self._body.setMaximumHeight(0)
        self._body.setMinimumHeight(0)
        root.addWidget(self._body)

        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(70)
        self._flush_timer.timeout.connect(self._flush)

        self._anim = QPropertyAnimation(self._body, b"maximumHeight", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.reset()

    # ---- public state --------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not enabled:
            self.reset()
            self._toggle.setText("思考已关闭")
            self._status.setText("可在设置 → 分析中开启")
            set_tone(self._status, "muted")

    def set_auto_collapse(self, auto: bool) -> None:
        self._auto_collapse = bool(auto)

    def begin(self) -> None:
        if not self._enabled:
            return
        self._flush_timer.stop()
        self._buffer = ""
        self._streamed = False
        self._started = time.monotonic()
        self._body.clear()
        self._toggle.setText("深度思考中…")
        self._status.setText("实时推理")
        set_tone(self._status, "cyan")
        self._dot.set_color(CYAN)
        self._dot.set_pulse(True)
        self._set_expanded(True)
        self._hint.setText("实时")

    def mark_pending(self, text: str = "解读中…", status: str = "快速模式") -> None:
        """Fast mode: show that a decode is running without faking a live stream."""
        if not self._enabled:
            return
        self._started = time.monotonic()
        self._toggle.setText(text)
        self._status.setText(status)
        set_tone(self._status, "cyan")
        self._dot.set_color(CYAN)
        self._dot.set_pulse(True)

    def append(self, delta: str) -> None:
        if not delta:
            return
        self._buffer += delta
        self._streamed = True
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def finish(
        self,
        steps: list[str] | None = None,
        elapsed: float | None = None,
        deep: bool | None = None,
    ) -> None:
        if not self._enabled:
            return
        self._flush_timer.stop()
        self._flush()
        if elapsed is None:
            elapsed = time.monotonic() - (self._started or time.monotonic())
        had_content = bool(self._body.toPlainText().strip()) or bool(steps)
        text = self._body.toPlainText().strip()
        if not text:
            if steps:
                text = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))
            else:
                text = "本次模型没有返回可展示的思考内容。"
            self._body.setPlainText(text)
        if deep is False:
            toggle_text = f"解读完成（{elapsed:.1f}s）"
            status_text = "思考摘要" if had_content else "无思考摘要"
        else:
            toggle_text = (
                f"已深度思考（{elapsed:.1f}s）" if had_content else f"分析完成（{elapsed:.1f}s）"
            )
            status_text = "模型思考路径" if had_content else "无思考内容"
        self._toggle.setText(toggle_text)
        self._status.setText(status_text)
        set_tone(self._status, "muted")
        self._dot.set_color(GREEN)
        self._dot.set_pulse(False)
        if self._auto_collapse:
            self._set_expanded(False)
        else:
            self._set_expanded(True)
            self._hint.setText("点击收起")

    def abort(self, message: str = "已中断") -> None:
        if not self._enabled:
            return
        self._flush_timer.stop()
        self._flush()
        self._toggle.setText("思考中断")
        self._status.setText(message)
        set_tone(self._status, "amber")
        self._dot.set_color(AMBER)
        self._dot.set_pulse(False)
        if self._auto_collapse:
            self._set_expanded(False)
        self._hint.setText("点击查看")

    def reset(self) -> None:
        self._flush_timer.stop()
        self._buffer = ""
        self._streamed = False
        self._started = None
        self._body.clear()
        self._toggle.setText("深度思考")
        self._status.setText("等待解读" if self._enabled else "未启用")
        set_tone(self._status, "muted")
        self._dot.set_color(MUTED)
        self._dot.set_pulse(False)
        self._hint.setText("点击展开")
        self._set_expanded(False)
        self._hint.setText("")

    # ---- internals -----------------------------------------------------------

    def _on_toggle_clicked(self) -> None:
        if not self._body.toPlainText().strip() and not self._buffer:
            return
        self._set_expanded(not self._expanded)

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow
        )
        if expanded or self._body.toPlainText().strip() or self._buffer:
            self._hint.setText("点击收起" if self._expanded else "点击展开")
        target = 190 if self._expanded else 0
        if self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._body.maximumHeight())
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._body.setMaximumHeight(target)

    def _flush(self) -> None:
        if not self._buffer:
            return
        text = self._buffer
        self._buffer = ""
        scrollbar = self._body.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 8
        cursor = self._body.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._body.setTextCursor(cursor)
        self._body.insertPlainText(text)
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())


class StageStepper(QWidget):
    """Compact five-node pipeline indicator painted by hand."""

    def __init__(self, stages=None, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(46)
        self.setMinimumWidth(260)
        self._defs = tuple(stages or STAGE_DEFS)
        self._states = {name: "idle" for name, _ in self._defs}

    def set_stage(self, stage: str, state: str) -> None:
        if stage not in self._states:
            return
        if self._states[stage] == state:
            return
        self._states[stage] = state
        self.update()

    def reset(self) -> None:
        self._states = {name: "idle" for name, _ in self._defs}
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        margin = 28
        step = (width - margin * 2) / max(1, len(self._defs) - 1)
        y = 13

        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(9)
        painter.setFont(font)

        # connectors first
        for index in range(len(self._defs) - 1):
            x1 = margin + index * step
            x2 = margin + (index + 1) * step
            left = self._states[self._defs[index][0]]
            right = self._states[self._defs[index + 1][0]]
            if left == "done" and right in ("done", "active"):
                color = QColor(52, 211, 153, 150)
            elif left == "error" or right == "error":
                color = QColor(248, 113, 113, 90)
            else:
                color = QColor(255, 255, 255, 24)
            painter.setPen(QPen(color, 1.2))
            painter.drawLine(int(x1 + 8), y, int(x2 - 8), y)

        for index, (name, label) in enumerate(self._defs):
            x = margin + index * step
            state = self._states[name]
            color = _STAGE_COLORS.get(state, _STAGE_COLORS["idle"])
            if state == "active":
                halo = QColor(color.red(), color.green(), color.blue(), 46)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(QRectF(x - 7, y - 7, 14, 14))
                painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 160), 1.2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QRectF(x - 7, y - 7, 14, 14))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(x - 3.6, y - 3.6, 7.2, 7.2))
            if state == "done":
                pen = QPen(QColor("#04110c"), 1.1)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(int(x - 1.6), int(y), int(x - 0.3), int(y + 1.4))
                painter.drawLine(int(x - 0.3), int(y + 1.4), int(x + 2.0), int(y - 1.4))

            if state in ("active", "done"):
                painter.setPen(QColor("#c7d6e8"))
            elif state == "error":
                painter.setPen(QColor("#fca5a5"))
            else:
                painter.setPen(QColor("#66738a"))
            rect = QRectF(x - step / 2, 24, step, 18)
            painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)
        painter.end()


class PipelineLog(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        dot = GlowDot(GREEN, size=9)
        title = QLabel("pipeline.log")
        title.setObjectName("logTitle")
        self._meta = QLabel("latest-only · max 1 在途")
        self._meta.setObjectName("logMeta")
        head.addWidget(dot)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._meta)
        layout.addLayout(head)

        self._view = QPlainTextEdit()
        self._view.setObjectName("pipelineLog")
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._view.setMaximumBlockCount(400)
        self._view.setPlaceholderText("等待流水线事件…")
        layout.addWidget(self._view, 1)

    def append(self, line: str) -> None:
        scrollbar = self._view.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 8
        self._view.appendPlainText(line)
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def clear(self) -> None:
        self._view.clear()

    def set_meta(self, text: str) -> None:
        self._meta.setText(text)


class PipelinePanel(QWidget):
    def __init__(self, stages=None, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.stepper = StageStepper(stages)
        self.log = PipelineLog()
        layout.addWidget(self.stepper)
        layout.addWidget(self.log, 1)

    def set_stage(self, stage: str, state: str) -> None:
        self.stepper.set_stage(stage, state)

    def reset_stages(self) -> None:
        self.stepper.reset()

    def append_log(self, line: str) -> None:
        self.log.append(line)

    def set_meta(self, text: str) -> None:
        self.log.set_meta(text)


class ImagePreview(QWidget):
    """Paint the current local frame at the display size."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._placeholder = ""
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_frame(self, image) -> None:
        if image is None:
            self.clear()
            return
        if isinstance(image, QImage):
            self._pixmap = QPixmap.fromImage(image)
            self.update()
            return
        try:
            import numpy as np

            array = np.asarray(image)
            if array.ndim != 3 or array.shape[2] < 3:
                raise ValueError("unsupported frame")
            array = np.ascontiguousarray(array[:, :, :3], dtype=np.uint8)
            height, width = array.shape[:2]
            qimage = QImage(
                array.data,
                width,
                height,
                int(array.strides[0]),
                QImage.Format.Format_RGB888,
            ).copy()
            self._pixmap = QPixmap.fromImage(qimage)
        except Exception:
            self._pixmap = None
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, QColor(255, 255, 255, 8))
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
        painter.drawPath(path)

        if self._pixmap is not None and not self._pixmap.isNull():
            inner = rect.adjusted(6, 6, -6, -6)
            size = self._pixmap.size().scaled(inner.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, size.width(), size.height())
            target.moveCenter(inner.center())
            painter.save()
            painter.setClipPath(path)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
            painter.restore()
        else:
            painter.setPen(QColor("#5f6d83"))
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(11)
            painter.setFont(font)
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                self._placeholder or "点击「开始采集」查看实时画面",
            )
        painter.end()

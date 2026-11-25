"""Custom-painted widgets that give the panel its dark-glass look.

QSS can style boxes and text but cannot draw gradients, arcs or pulses, so the
few "expensive" details live here: the ambient backdrop, the brand mark, glowing
status dots, the emotion confidence ring, the indeterminate update bar and the
card shell used by every section.
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

CYAN = QColor("#67e8f9")
INDIGO = QColor("#818cf8")
VIOLET = QColor("#c084fc")
AMBER = QColor("#fbbf24")
GREEN = QColor("#34d399")
RED = QColor("#f87171")
MUTED = QColor("#7c899e")

TONE_COLORS: dict[str, QColor] = {
    "cyan": CYAN,
    "indigo": INDIGO,
    "violet": VIOLET,
    "amber": AMBER,
    "green": GREEN,
    "red": RED,
    "muted": MUTED,
    "gray": MUTED,
}


def tone_for_state(text: str) -> str:
    """Map a scheduler state label to a visual tone."""
    if "完成" in text or text.startswith("已采集"):
        return "green"
    if "错误" in text or "失败" in text:
        return "red"
    if "暂停" in text or "等待" in text:
        return "amber"
    if "收尾" in text:
        return "amber"
    if "采集" in text:
        return "cyan"
    if "分析" in text or "OCR" in text or "选择" in text:
        return "cyan"
    if "监控" in text:
        return "green"
    return "gray"


def as_color(value: QColor | str) -> QColor:
    return value if isinstance(value, QColor) else QColor(value)


def set_tone(widget: QWidget, tone: str) -> None:
    """Update a QSS dynamic property and repolish so [tone="..."] selectors apply."""
    if widget.property("tone") == tone:
        return
    widget.setProperty("tone", tone)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _paint_brand(painter: QPainter, rect: QRectF) -> None:
    radius = rect.width() * 0.3
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor("#7df0ff"))
    gradient.setColorAt(0.55, QColor("#818cf8"))
    gradient.setColorAt(1.0, QColor("#d8a6ff"))
    painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
    painter.setBrush(QBrush(gradient))
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    # soft top highlight
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 26))
    painter.drawEllipse(
        QRectF(rect.left() + rect.width() * 0.22, rect.top() + rect.height() * 0.07,
               rect.width() * 0.56, rect.height() * 0.2)
    )

    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(max(10, int(rect.width() * 0.42)))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor("#06080f"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "外")


class Backdrop(QWidget):
    """Paints the ambient gradient + coloured glows behind the whole panel."""

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        width, height = max(1, rect.width()), max(1, rect.height())

        base = QLinearGradient(0, 0, 0, height)
        base.setColorAt(0.0, QColor("#0d1220"))
        base.setColorAt(0.55, QColor("#080b14"))
        base.setColorAt(1.0, QColor("#05070c"))
        painter.fillRect(rect, base)

        glows = (
            (width * 0.86, height * 0.06, max(width, height) * 0.62, QColor(99, 102, 241, 54)),
            (width * 0.02, height * 0.52, width * 1.05, QColor(34, 211, 238, 26)),
            (width * 0.92, height * 0.94, width * 0.85, QColor(192, 132, 252, 26)),
        )
        for cx, cy, radius, color in glows:
            glow = QRadialGradient(QPointF(cx, cy), max(1.0, radius))
            glow.setColorAt(0.0, color)
            glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawRect(rect)

        painter.setPen(QPen(QColor(255, 255, 255, 16), 1))
        painter.drawLine(14, 0, width - 14, 0)
        painter.end()


class BrandMark(QWidget):
    def __init__(self, size: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_brand(painter, QRectF(0, 0, self.width(), self.height()))
        painter.end()


class GlowDot(QWidget):
    """Small status dot with a soft halo; optionally breathing."""

    def __init__(
        self,
        color: QColor | str = CYAN,
        size: int = 10,
        pulse: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = as_color(color)
        self._pulse = pulse
        self._phase = 0.0
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._tick)
        if pulse:
            self._timer.start()

    def set_color(self, color: QColor | str) -> None:
        self._color = as_color(color)
        self.update()

    def set_pulse(self, pulse: bool) -> None:
        self._pulse = pulse
        if pulse:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase += 0.16
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height())
        center = QPointF(size / 2.0, size / 2.0)
        color = self._color

        if self._pulse:
            alpha = int(58 + 58 * (0.5 + 0.5 * math.sin(self._phase)))
        else:
            alpha = 70
        halo = QRadialGradient(center, max(1.0, size / 2.0))
        halo.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), alpha))
        halo.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(QRectF(0, 0, size, size))

        radius = size * 0.23
        painter.setBrush(color)
        painter.drawEllipse(center, radius, radius)
        painter.end()


class ElidedLabel(QLabel):
    """QLabel that elides its text instead of clipping when space is tight."""

    def __init__(
        self,
        text: str = "",
        color: QColor | str = "#9fe8f5",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._color = as_color(color)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_color(self, color: QColor | str) -> None:
        self._color = as_color(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setFont(self.font())
        metrics = painter.fontMetrics()
        text = metrics.elidedText(
            self.text(), Qt.TextElideMode.ElideRight, max(0, self.width())
        )
        painter.setPen(self._color)
        painter.drawText(
            QRectF(0, 0, self.width(), self.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            text,
        )
        painter.end()


class RingMeter(QWidget):
    """Circular confidence gauge drawn with a cyan → violet conical gradient."""

    def __init__(
        self,
        value: float | None = None,
        size: int = 46,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value = value
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_value(self, value: float | None) -> None:
        self._value = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        ring_rect = QRectF(3.5, 3.5, max(1, width - 7), max(1, height - 7))

        track = QPen(QColor(255, 255, 255, 26), 4.0)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(ring_rect)

        value = 0.0 if self._value is None else max(0.0, min(1.0, float(self._value)))
        if self._value is not None and value > 0:
            gradient = QConicalGradient(QPointF(width / 2.0, height / 2.0), 90.0)
            gradient.setColorAt(0.0, QColor("#67e8f9"))
            gradient.setColorAt(0.55, QColor("#818cf8"))
            gradient.setColorAt(1.0, QColor("#c084fc"))
            pen = QPen(QBrush(gradient), 4.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(ring_rect, 90 * 16, -int(value * 360 * 16))

        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(max(8, int(height * 0.2)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#e6eefc"))
        text = "—" if self._value is None else f"{round(value * 100)}%"
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class PulseBar(QWidget):
    """Thin indeterminate progress bar with a moving gradient segment."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(3)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._pos = -0.4
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._pos = -0.4
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._pos += 0.013
        if self._pos > 1.3:
            self._pos = -0.4
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 16))
        painter.drawRoundedRect(QRectF(0, 1, width, 2), 1, 1)
        if self._active and width > 8:
            segment = max(28.0, width * 0.34)
            x = self._pos * width
            painter.setClipRect(self.rect())
            gradient = QLinearGradient(x, 0, x + segment, 0)
            gradient.setColorAt(0.0, QColor(103, 232, 249, 0))
            gradient.setColorAt(0.4, QColor("#67e8f9"))
            gradient.setColorAt(0.8, QColor("#818cf8"))
            gradient.setColorAt(1.0, QColor(192, 132, 252, 0))
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(QRectF(x, 1, segment, 2), 1, 1)
        painter.end()


class SectionCard(QFrame):
    """Bordered glass card with a coloured dot, title, hint and a body area."""

    def __init__(
        self,
        title: str,
        hint: str = "",
        accent: QColor | str = CYAN,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(7)
        self._dot = GlowDot(accent, size=10, pulse=False, parent=self)
        header.addWidget(self._dot)
        self._title = QLabel(title)
        self._title.setObjectName("sectionTitle")
        header.addWidget(self._title)
        header.addStretch(1)
        self._hint = QLabel(hint)
        self._hint.setObjectName("sectionHint")
        header.addWidget(self._hint)
        root.addLayout(header)

        self.body = QWidget(self)
        self.body.setObjectName("sectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        root.addWidget(self.body, 1)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body_layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self.body_layout.addLayout(layout)

    def set_hint(self, text: str) -> None:
        self._hint.setText(text)


def app_icon() -> QIcon:
    """Prefer the multi-size .ico asset; fall back to a painted mark."""
    if QGuiApplication.instance() is None:
        return QIcon()
    icon_path = Path(__file__).resolve().parents[2] / "assets" / "app.ico"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _paint_brand(painter, QRectF(4, 4, 56, 56))
    painter.end()
    return QIcon(pixmap)


def _render_icon(draw, color: QColor | str, size: int) -> QIcon:
    if QGuiApplication.instance() is None:
        return QIcon()
    tint = as_color(color)
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(ratio, ratio)
    draw(painter, float(size), tint)
    painter.end()
    return QIcon(pixmap)


def crosshair_icon(color: QColor | str = "#05070c", size: int = 16) -> QIcon:
    """Region-selection target icon."""

    def draw(painter: QPainter, s: float, tint: QColor) -> None:
        pen = QPen(tint, 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(s * 0.25, s * 0.25, s * 0.5, s * 0.5))
        mid = s / 2
        painter.drawLine(QPointF(mid, 1.5), QPointF(mid, 4.4))
        painter.drawLine(QPointF(mid, s - 4.4), QPointF(mid, s - 1.5))
        painter.drawLine(QPointF(1.5, mid), QPointF(4.4, mid))
        painter.drawLine(QPointF(s - 4.4, mid), QPointF(s - 1.5, mid))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        painter.drawEllipse(QPointF(mid, mid), 1.2, 1.2)

    return _render_icon(draw, color, size)


def pause_icon(color: QColor | str = "#c9d4e5", size: int = 16) -> QIcon:
    """Two rounded bars used by the pause / resume button."""

    def draw(painter: QPainter, s: float, tint: QColor) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        width = s * 0.17
        height = s * 0.58
        top = (s - height) / 2
        painter.drawRoundedRect(QRectF(s * 0.3, top, width, height), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(s * 0.53, top, width, height), 1.2, 1.2)

    return _render_icon(draw, color, size)

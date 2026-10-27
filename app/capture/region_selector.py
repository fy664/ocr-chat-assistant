"""Full-screen semi-transparent region selector (PySide6 overlay).

One overlay window per monitor. The user drags a rectangle, sees its size
live, confirms with Enter and cancels with Esc. The result is converted
from Qt logical coordinates to *physical* pixels (mss space) using the
screen's devicePixelRatio - valid for the common uniform-scaling Windows
case, with the coordinate model kept correct for multi-monitor setups.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, QRectF, QObject, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPen,
    QScreen,
)
from PySide6.QtWidgets import QApplication, QWidget

from app.models.schemas import ScreenRegion

logger = logging.getLogger("ocr_chat.region_selector")

MIN_SELECT_SIZE = 5

MASK_COLOR = QColor(3, 5, 10, 172)
BORDER_COLOR = QColor("#67e8f9")
TEXT_COLOR = QColor("#eef3ff")
PILL_BG = QColor(8, 12, 20, 228)


class OverlayWindow(QWidget):
    def __init__(self, screen: QScreen, on_finish) -> None:
        super().__init__(None)
        self._screen = screen
        self._on_finish = on_finish
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(screen.geometry())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
        self.setFocus()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), MASK_COLOR)

        rect = self._selection_rect()
        if rect is not None:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(103, 232, 249, 55), 6))
            painter.drawRect(rect.adjusted(-3, -3, 3, 3))
            painter.setPen(QPen(BORDER_COLOR, 1.4))
            painter.drawRect(rect)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(BORDER_COLOR)
            for corner in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                painter.drawRoundedRect(
                    QRectF(corner.x() - 3, corner.y() - 3, 6, 6), 1.5, 1.5
                )

            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(10)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            size_text = f"{rect.width()} × {rect.height()}"
            pill_w = metrics.horizontalAdvance(size_text) + 18
            pill_h = 22
            pill_x = max(12, min(rect.right() - pill_w, self.width() - pill_w - 12))
            pill_y = rect.top() + 8
            if pill_y + pill_h > self.height() - 12:
                pill_y = max(12, rect.bottom() - pill_h - 8)
            pill_rect = QRectF(pill_x, pill_y, pill_w, pill_h)
            painter.setBrush(PILL_BG)
            painter.setPen(QPen(QColor(103, 232, 249, 70), 1))
            painter.drawRoundedRect(pill_rect, 7, 7)
            painter.setPen(TEXT_COLOR)
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, size_text)

        hint_font = QFont("Microsoft YaHei UI")
        hint_font.setPixelSize(11)
        painter.setFont(hint_font)
        metrics = QFontMetrics(hint_font)
        hint = "拖动框选聊天区域   ·   Enter 确认   ·   Esc 取消"
        hint = metrics.elidedText(hint, Qt.TextElideMode.ElideRight, max(160, self.width() - 90))
        hint_w = metrics.horizontalAdvance(hint) + 36
        hint_rect = QRectF((self.width() - hint_w) / 2, 26, hint_w, 36)
        painter.setBrush(PILL_BG)
        painter.setPen(QPen(QColor(255, 255, 255, 34), 1))
        painter.drawRoundedRect(hint_rect, 12, 12)
        painter.setPen(TEXT_COLOR)
        painter.drawText(hint_rect, Qt.AlignmentFlag.AlignCenter, hint)
        painter.end()

    def _selection_rect(self) -> QRect | None:
        if self._start is None or self._current is None:
            return None
        return QRect(self._start, self._current).normalized()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._current = self._start
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._finish(None)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._start is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._current = event.position().toPoint()
            self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            rect = self._selection_rect()
            if rect is not None and rect.width() >= MIN_SELECT_SIZE and rect.height() >= MIN_SELECT_SIZE:
                self._finish(rect)
        elif event.key() == Qt.Key.Key_Escape:
            self._finish(None)

    def _finish(self, rect: QRect | None) -> None:
        if self._on_finish is None:
            return
        callback, self._on_finish = self._on_finish, None
        callback(self._screen, rect)


class RegionSelector(QObject):
    """Opens overlays on every monitor; emits a ScreenRegion (physical px) or cancels."""

    region_selected = Signal(object)   # ScreenRegion
    selection_cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._overlays: list[OverlayWindow] = []
        self._finished = False

    @property
    def is_active(self) -> bool:
        return bool(self._overlays)

    def start(self) -> None:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("RegionSelector requires a QApplication")
        screens: list[QScreen] = QGuiApplication.screens() or [app.primaryScreen()]
        for screen in screens:
            overlay = OverlayWindow(screen, self._on_overlay_finish)
            overlay.show()
            overlay.raise_()
            self._overlays.append(overlay)
        logger.info("region selector opened on %d screen(s)", len(screens))

    def cancel(self) -> None:
        self._close_all()
        if not self._finished:
            self._finished = True
            self.selection_cancelled.emit()

    def _on_overlay_finish(self, screen: QScreen, rect: QRect | None) -> None:
        if self._finished:
            self._close_all()
            return
        self._finished = True
        self._close_all()
        if rect is None:
            self.selection_cancelled.emit()
            return
        region = self._to_physical(screen, rect)
        logger.info("region selected: %s", region.model_dump())
        self.region_selected.emit(region)

    @staticmethod
    def _to_physical(screen: QScreen, rect: QRect) -> ScreenRegion:
        dpr = screen.devicePixelRatio()
        geo = screen.geometry()
        x = round((geo.x() + rect.x()) * dpr)
        y = round((geo.y() + rect.y()) * dpr)
        w = round(rect.width() * dpr)
        h = round(rect.height() * dpr)
        return ScreenRegion(x=x, y=y, width=max(1, w), height=max(1, h))

    def _close_all(self) -> None:
        for overlay in self._overlays:
            try:
                overlay.close()
            except Exception:
                pass
        self._overlays = []

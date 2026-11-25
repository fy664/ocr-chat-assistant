"""Choose a source window and mark the OCR area on its own preview."""
from __future__ import annotations

from math import ceil, floor

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.capture.screen_capture import CaptureError
from app.capture.window_capture import WindowFeed, WindowSelection, window_choices
from app.models.schemas import ScreenRegion


class CropPreview(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.region: ScreenRegion | None = None
        self.marker: ScreenRegion | None = None
        self.marking_title = False
        self._press: QPointF | None = None
        self._drag: QPointF | None = None
        self.setMinimumSize(480, 300)
        self.setAccessibleName("窗口预览，拖动框选聊天区域")
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_image(self, image: QImage) -> None:
        self.image = image
        self.region = self.marker = None
        self.marking_title = False
        self._press = self._drag = None
        self.update()
        self.changed.emit()

    def _drawn_rect(self) -> QRectF:
        size = QSizeF(self.image.size())
        size.scale(QSizeF(self.size()), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                      size.width(), size.height())

    def _to_image_region(self, start: QPointF, end: QPointF) -> ScreenRegion | None:
        drawn = self._drawn_rect()
        selection = QRectF(start, end).normalized().intersected(drawn)
        if selection.width() < 3 or selection.height() < 3:
            return None
        sx, sy = self.image.width() / drawn.width(), self.image.height() / drawn.height()
        x = max(0, floor((selection.left() - drawn.left()) * sx))
        y = max(0, floor((selection.top() - drawn.top()) * sy))
        right = min(self.image.width(), ceil((selection.right() - drawn.left()) * sx))
        bottom = min(self.image.height(), ceil((selection.bottom() - drawn.top()) * sy))
        return ScreenRegion(x=x, y=y, width=right - x, height=bottom - y)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#131821"))
        if self.image.isNull():
            return
        rect = self._drawn_rect()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(rect, self.image)
        sx, sy = rect.width() / self.image.width(), rect.height() / self.image.height()
        for region, color in ((self.region, "#35d5e8"), (self.marker, "#fbbf66")):
            if region is not None:
                painter.setPen(QPen(QColor(color), 2))
                painter.drawRect(QRectF(rect.x() + region.x * sx, rect.y() + region.y * sy,
                                        region.width * sx, region.height * sy))
        if self._press is not None and self._drag is not None:
            color = "#fbbf66" if self.marking_title else "#35d5e8"
            painter.setPen(QPen(QColor(color), 2, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(self._press, self._drag).normalized().intersected(rect))

    def mousePressEvent(self, event):  # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton and not self.image.isNull()
                and self._drawn_rect().contains(event.position())):
            self._press = self._drag = event.position()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press is not None:
            self._drag = event.position()
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._press is None or event.button() != Qt.MouseButton.LeftButton:
            return
        selection = self._to_image_region(self._press, event.position())
        self._press = self._drag = None
        if selection is not None:
            if self.marking_title:
                self.marker = selection
                self.marking_title = False
            else:
                self.region = selection
            self.changed.emit()
        self.update()


class WindowPicker(QDialog):
    UseDesktop = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择采集窗口")
        self.resize(850, 607)
        self.selection: WindowSelection | None = None
        self._feed: WindowFeed | None = None
        self._native_size: tuple[int, int] | None = None

        self._list = QComboBox()
        self._list.setAccessibleName("可采集窗口")
        self._list.currentIndexChanged.connect(self._open_preview)
        refresh = QPushButton("刷新窗口列表")
        refresh.clicked.connect(self._refresh)
        sources = QHBoxLayout()
        sources.addWidget(self._list, 1)
        sources.addWidget(refresh)

        self._preview = CropPreview(self)
        self._preview.changed.connect(self._update_controls)
        self._hint = QLabel("先选择聊天窗口，再在预览里拖动框选消息区。")
        self._hint.setWordWrap(True)
        self._marker_button = QPushButton("框选会话标题")
        self._marker_button.setToolTip("可选。框选固定的联系人或群名，内容改变时暂停采集。")
        self._marker_button.clicked.connect(self._mark_title)
        self._clear_marker = QPushButton("清除标题选区")
        self._clear_marker.clicked.connect(self._remove_marker)
        desktop = QPushButton("改用屏幕框选")
        desktop.clicked.connect(lambda: self.done(self.UseDesktop))
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        self._ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("使用此选区")
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(desktop)
        actions.addWidget(self._marker_button)
        actions.addWidget(self._clear_marker)
        actions.addStretch()
        actions.addWidget(self._buttons)

        layout = QVBoxLayout(self)
        layout.addLayout(sources)
        layout.addWidget(self._hint)
        layout.addWidget(self._preview, 1)
        layout.addLayout(actions)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll_preview)
        self._refresh()

    def _refresh(self) -> None:
        self._close_preview()
        self._list.blockSignals(True)
        try:
            self._list.clear()
            self._list.addItem("选择聊天窗口…")
            title = self.parentWidget().windowTitle() if self.parentWidget() is not None else ""
            for choice in window_choices(title):
                self._list.addItem(choice.title, choice)
        finally:
            self._list.blockSignals(False)
        self._open_preview()
        if self._list.count() == 1:
            self._hint.setText("没有可采集窗口。打开聊天窗口后刷新，或选择屏幕框选。")

    def _open_preview(self) -> None:
        self._close_preview()
        self._preview.set_image(QImage())
        target = self._list.currentData()
        if target is None:
            self._hint.setText("先选择聊天窗口，再在预览里拖动框选消息区。")
            return
        self._feed = WindowFeed(target, self)
        self._feed.start()
        self._hint.setText("正在等待窗口画面…")
        self._timer.start()

    def _poll_preview(self) -> None:
        if self._feed is None:
            return
        image, reason = self._feed.snapshot()
        if reason:
            self._hint.setText(reason)
            return
        self._native_size = self._feed.target.native_size()
        self._preview.set_image(image)
        self._timer.stop()

    def _update_controls(self) -> None:
        preview = self._preview
        self._ok.setEnabled(preview.region is not None and not preview.marking_title)
        self._marker_button.setEnabled(preview.region is not None)
        self._marker_button.setText("取消标题框选" if preview.marking_title else "框选会话标题")
        self._clear_marker.setVisible(preview.marker is not None)
        if preview.marking_title:
            self._hint.setText("请拖动框选联系人或群名，避开会闪动的图标和数字。")
        elif preview.region is not None:
            hint = "蓝框内为聊天消息区。可选：框选固定的会话标题，切换会话时会暂停。"
            if preview.marker is not None:
                hint = "蓝框内为消息区，橙框内为会话标题。"
            self._hint.setText(hint)
        elif not preview.image.isNull():
            self._hint.setText("拖动框选消息区，尽量避开侧栏、滚动条和输入框。")

    def _mark_title(self) -> None:
        self._preview.marking_title = not self._preview.marking_title
        self._update_controls()

    def _remove_marker(self) -> None:
        self._preview.marker = None
        self._preview.marking_title = False
        self._preview.update()
        self._update_controls()

    def accept(self) -> None:
        if self._feed is None or self._preview.region is None or self._preview.marking_title:
            return
        target = self._feed.target
        current, problem = self._feed.snapshot()
        if (problem or current.size() != self._preview.image.size()
                or target.native_size() != self._native_size):
            self._open_preview()
            self._hint.setText(problem or "窗口已变化，请在新预览里重新框选。")
            return
        try:
            self.selection = WindowSelection.from_preview(
                target, self._preview.image, self._preview.region, self._preview.marker,
            )
        except CaptureError as exc:
            self._hint.setText(str(exc))
            return
        super().accept()

    def done(self, result: int) -> None:
        self._close_preview()
        super().done(result)

    def _close_preview(self) -> None:
        self._timer.stop()
        feed, self._feed = self._feed, None
        if feed is not None:
            feed.close()

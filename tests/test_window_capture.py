from threading import Event

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QImage, QPainter

import app.analysis.decoder as decoder_module
import app.ui.window_picker as picker_module
from app.analysis.decoder import DecoderController
from app.capture.screen_capture import CaptureError
from app.capture.window_capture import WindowRegionCapture, WindowSelection
from app.models.schemas import ScreenRegion
from app.ui.decoder_window import DecoderWindow
from app.ui.window_picker import CropPreview, WindowPicker
from tests.helpers import StubOCREngine, wait_until


REGION = ScreenRegion(x=10, y=22, width=25, height=20)
MARKER = ScreenRegion(x=5, y=3, width=20, height=8)


class Target:
    title = "合成聊天窗口"
    size = (100, 70)
    closed = False

    def native_size(self):
        return self.size


class Feed:
    def __init__(self, target, parent=None):
        self.target = target
        self.image = scene("#8cd258")
        self.reason = ""
        self.error = ""
        self.closed = False

    def start(self):
        pass

    def snapshot(self):
        return self.image, self.reason

    def close(self):
        self.closed = True


def scene(body, marker="#eeeeee", width=90):
    image = QImage(width, 60, QImage.Format.Format_RGB32)
    image.fill(QColor("#243040"))
    painter = QPainter(image)
    painter.fillRect(QRect(REGION.x, REGION.y, REGION.width, REGION.height), QColor(body))
    painter.fillRect(QRect(MARKER.x, MARKER.y, MARKER.width, MARKER.height), QColor(marker))
    painter.end()
    return image


def test_window_crop_only_passes_selected_pixels_and_rejects_changed_title():
    feed = Feed(Target())
    selected = WindowSelection.from_preview(feed.target, feed.image, REGION, MARKER)
    capture = WindowRegionCapture(selected, feed)
    frame = capture.capture(REGION)
    assert frame.image.flags.c_contiguous
    np.testing.assert_array_equal(frame.image[0, 0], [140, 210, 88])
    assert frame.image.shape == (20, 25, 3)

    feed.image = scene("#13568e")
    np.testing.assert_array_equal(capture.capture(REGION).image[-1, -1], [19, 86, 142])
    feed.image = scene("#13568e", "#00ffff")
    with pytest.raises(CaptureError, match="会话标题区域已变化"):
        capture.capture(REGION)


@pytest.mark.parametrize("stale_frame", [True, False])
def test_window_resize_rejects_current_or_stale_frames(stale_frame):
    feed = Feed(Target())
    selected = WindowSelection.from_preview(feed.target, feed.image, REGION)
    capture = WindowRegionCapture(selected, feed)
    if stale_frame:
        feed.target.size = (120, 70)
    else:
        feed.image = scene("#8cd258", width=125)
    with pytest.raises(CaptureError, match="尺寸或缩放已变化"):
        capture.capture(REGION)


def test_preview_maps_reverse_drag_from_letterboxed_widget_to_image(qapp):
    preview = CropPreview()
    preview.resize(480, 300)
    preview.set_image(QImage(800, 400, QImage.Format.Format_RGB32))
    region = preview._to_image_region(QPointF(360, 210), QPointF(120, 90))
    assert region == ScreenRegion(x=200, y=100, width=400, height=200)
    preview.close()


def test_picker_keeps_window_and_both_crops_and_releases_preview(qapp, monkeypatch):
    target = Target()
    monkeypatch.setattr(picker_module, "window_choices", lambda _title: [target])
    monkeypatch.setattr(picker_module, "WindowFeed", Feed)
    dialog = WindowPicker()
    dialog._list.setCurrentIndex(1)
    feed = dialog._feed
    dialog._poll_preview()
    dialog._preview.region = REGION
    dialog._update_controls()
    dialog._marker_button.click()
    assert not dialog._ok.isEnabled()
    dialog._marker_button.click()
    assert dialog._ok.isEnabled()
    dialog._preview.marker = MARKER
    dialog.accept()
    assert dialog.selection.target is target
    assert dialog.selection.region == REGION
    assert dialog.selection.marker == MARKER
    assert feed.closed


def test_controller_reuses_window_source_for_single_and_rolling_capture(qapp, make_settings, monkeypatch):
    target = Target()
    feeds = []

    def create_capture(selection):
        feed = Feed(target)
        feeds.append(feed)
        return WindowRegionCapture(selection, feed)

    monkeypatch.setattr(decoder_module, "WindowRegionCapture", create_capture)
    settings = make_settings(vision_enabled=False, scroll_capture_interval_ms=100)
    engine = StubOCREngine(["第一张聊天截图", "第二张聊天截图"])
    controller = DecoderController(settings, mock_llm=True, ocr_engine_factory=lambda: engine)
    selected = WindowSelection.from_preview(target, scene("#8cd258"), REGION)
    one_shot, collections = [], []
    controller.capture_completed.connect(one_shot.append)
    controller.collection_completed.connect(collections.append)
    try:
        controller.set_window_selection(selected)
        controller.capture(REGION)
        assert wait_until(qapp, lambda: one_shot)
        assert one_shot == ["第一张聊天截图"]
        assert feeds[0].closed

        assert controller.start_collection(REGION)
        assert wait_until(qapp, lambda: controller.stitcher and controller.stitcher.page_count == 1)
        controller.stop_collection()
        assert feeds[1].closed
        assert wait_until(qapp, lambda: collections)
        assert collections[0]["text"] == "第二张聊天截图"
        target.closed = True
        assert controller.start_collection(REGION)
        feeds[2].reason = "所选窗口已关闭"
        assert wait_until(qapp, lambda: len(collections) == 2)
        assert feeds[2].closed
        assert controller.window_selection is None
    finally:
        controller.shutdown()



def test_live_view_keeps_up_while_ocr_is_busy_and_clears_on_pause(qapp, make_settings, monkeypatch):
    feed = Feed(Target())
    monkeypatch.setattr(
        decoder_module, "WindowRegionCapture", lambda selection: WindowRegionCapture(selection, feed)
    )
    selected = WindowSelection.from_preview(feed.target, feed.image, REGION, MARKER)
    settings = make_settings(vision_enabled=False, scroll_capture_interval_ms=60_000)
    entered, release = Event(), Event()

    class BusyEngine(StubOCREngine):
        def recognize(self, image):
            entered.set()
            release.wait(5)
            return super().recognize(image)

    engine = BusyEngine(["用于测试的消息"])
    controller = DecoderController(settings, mock_llm=True, ocr_engine_factory=lambda: engine)
    window = DecoderWindow(controller, settings)
    completed = []
    controller.collection_completed.connect(completed.append)

    def preview_color():
        pixmap = window._preview._pixmap
        if pixmap is None:
            return None
        assert (pixmap.width(), pixmap.height()) == (REGION.width, REGION.height)
        return pixmap.toImage().pixelColor(2, 2).name()

    try:
        controller.set_window_selection(selected)
        window._tools_tabs.setCurrentIndex(1)
        assert controller.start_collection(REGION)
        session = controller._session
        assert window._tools_tabs.currentIndex() == 0
        assert wait_until(qapp, lambda: preview_color() == "#8cd258")
        session._monitor._tick()
        assert entered.wait(1)
        feed.image = scene("#13568e")
        assert wait_until(qapp, lambda: preview_color() == "#13568e")
        assert engine.calls == 0
        assert "实时画面" in window._vision_caption.text()

        feed.image = scene("#ff2255", marker="#00ffff")
        assert wait_until(qapp, lambda: "已暂停" in window._vision_caption.text())
        assert preview_color() is None
        feed.image = scene("#6945a8")
        assert wait_until(qapp, lambda: preview_color() == "#6945a8")

        release.set()
        controller.stop_collection()
        assert feed.closed
        assert not session._preview_timer.isActive()
        assert preview_color() is None
        assert wait_until(qapp, lambda: completed)
    finally:
        release.set()
        window.close()
        controller.shutdown()

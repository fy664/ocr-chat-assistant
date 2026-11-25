"""UI-level tests for the v2.1 「滚动采集」 strip.

The real DecoderController is used with a stub OCR engine and a fake capture
session, so the tests exercise the actual signal wiring, the editor replacement
and the copy/export paths without capturing the screen or loading PaddleOCR.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from app.analysis.decoder import DecoderController
from app.models.schemas import ScreenRegion
from app.ui import decoder_window as dw
from app.ui.decoder_window import DecoderWindow
from app.ui.widgets import tone_for_state
from tests.helpers import StubOCREngine, make_frame, wait_until

REGION = ScreenRegion(x=100, y=100, width=400, height=300)

PAGE_TEXTS = [
    "甲：明天几点开会\n乙：九点半\n甲：会议室在二楼",
    "乙：九点半\n甲：会议室在二楼\n乙：知道了",
    "甲：会议室在二楼\n乙：知道了\n甲：别迟到",
]

EXPECTED = [
    "甲：明天几点开会",
    "乙：九点半",
    "甲：会议室在二楼",
    "乙：知道了",
    "甲：别迟到",
]


class FakeSession(QObject):
    """Minimal stand-in for CaptureSession; the test drives its signals."""

    frame_ready = Signal(object, int)
    paused = Signal(str)
    resumed = Signal()
    state_changed = Signal(str)
    error = Signal(str)
    status_changed = Signal(dict)

    def __init__(self, region):
        super().__init__()
        self.region = region
        self.started = False
        self.stopped = False
        self.closed = False
        self.final = None

    def start(self):
        self.started = True
        self.state_changed.emit("采集中")

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    def capture_now(self):
        return self.final


class FakeSelector(QObject):
    """Stand-in for RegionSelector so no fullscreen overlay is created."""

    region_selected = Signal(object)
    selection_cancelled = Signal()
    instances: list["FakeSelector"] = []

    def __init__(self, parent=None):
        super().__init__(parent)
        FakeSelector.instances.append(self)
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def emit_region(self, region=REGION):
        self.region_selected.emit(region)

    def emit_cancel(self):
        self.selection_cancelled.emit()


@pytest.fixture()
def build_window(qapp, make_settings, monkeypatch):
    """Factory: controller + window sharing one stub OCR engine and session."""
    monkeypatch.setattr(dw, "RegionSelector", FakeSelector)
    FakeSelector.instances = []
    created: list[tuple] = []

    def _build(*, texts=None, editor_text="", vision_enabled=False):
        settings = make_settings(
            scroll_capture_interval_ms=700,
            scroll_max_queue=6,
            scroll_match_threshold=0.70,
            scroll_min_overlap_lines=2,
            vision_enabled=vision_enabled,
        )
        # An explicit empty list means "OCR returns nothing"; only None falls
        # back to the default pages, so the empty-result case is testable.
        engine = StubOCREngine(texts=PAGE_TEXTS if texts is None else list(texts))
        sessions: list[FakeSession] = []

        def session_factory(region):
            session = FakeSession(region)
            sessions.append(session)
            return session

        controller = DecoderController(
            settings,
            mock_llm=True,
            ocr_engine_factory=lambda: engine,
            session_factory=session_factory,
        )
        window = DecoderWindow(controller, settings)
        if editor_text:
            window._editor.setPlainText(editor_text)
        created.append((controller, window))
        return controller, window, engine, sessions

    yield _build

    # Tear down even when an assertion failed midway, otherwise the OCR thread
    # would outlive its controller and crash the interpreter at exit.
    for controller, window in created:
        try:
            window.close()
        except Exception:
            pass
        try:
            controller.shutdown()
        except Exception:
            pass


def test_collect_strip_is_present_and_calm_by_default(build_window):
    controller, window, _engine, _sessions = build_window()

    assert window._collect_button.objectName() == "collectStart"
    assert window._stop_collect_button.objectName() == "collectStop"
    assert window._collect_button.text() == "开始采集"
    assert window._stop_collect_button.text() == "结束采集"
    assert window._collect_button.isEnabled() is True
    assert window._stop_collect_button.isEnabled() is False
    assert "滚动采集" in window._collect_label.text()
    assert "不会持续监控" in window._region_label.text()
    window.close()
    controller.shutdown()


def test_collect_without_region_arms_then_autostarts_after_selection(
    build_window, qapp
):
    controller, window, engine, sessions = build_window()

    window._on_collect_clicked()
    assert window._pending_action == "collect"
    assert "框选" in window._collect_label.text()
    selector = FakeSelector.instances[-1]
    assert selector.started is True

    selector.emit_region()
    assert window._pending_action is None
    assert wait_until(qapp, lambda: controller.collecting, timeout_ms=3000)
    assert sessions and sessions[0].started is True
    assert window._collect_button.isEnabled() is False
    assert window._stop_collect_button.isEnabled() is True
    assert "采集中" in window._collect_label.text()

    window._on_stop_collect_clicked()
    assert wait_until(qapp, lambda: not controller.collecting, timeout_ms=5000)
    window.close()
    controller.shutdown()


def test_cancelled_selection_restores_idle_copy(build_window):
    controller, window, _engine, _sessions = build_window()

    window._on_collect_clicked()
    FakeSelector.instances[-1].emit_cancel()
    assert window._pending_action is None
    assert window._collect_label.text() == dw.COLLECT_IDLE_TEXT
    assert controller.collecting is False
    window.close()
    controller.shutdown()


def test_stop_writes_editor_and_keeps_undo(build_window, qapp):
    controller, window, engine, sessions = build_window(editor_text="旧的粘贴内容")
    assert controller.start_collection(REGION) is True
    session = sessions[0]

    for _ in range(len(PAGE_TEXTS)):
        session.frame_ready.emit(make_frame(), 1)
    assert wait_until(qapp, lambda: engine.calls == len(PAGE_TEXTS), timeout_ms=8000)

    session.final = make_frame()
    window._on_stop_collect_clicked()
    assert wait_until(
        qapp, lambda: window._editor.toPlainText().strip() != "旧的粘贴内容", 8000
    )

    assert window._editor.toPlainText().splitlines() == EXPECTED
    assert "已采集" in window._collect_label.text()
    assert window._collect_button.isEnabled() is True
    assert window._stop_collect_button.isEnabled() is False
    assert "5 行" in window._collect_badge.text()

    # The replacement is one undoable edit block.
    window._editor.undo()
    assert window._editor.toPlainText() == "旧的粘贴内容"
    window.close()
    controller.shutdown()


def test_empty_transcript_is_reported_without_clearing_editor(build_window, qapp):
    controller, window, _engine, sessions = build_window(texts=[], editor_text="保留我")
    assert controller.start_collection(REGION) is True
    session = sessions[0]
    session.frame_ready.emit(make_frame(), 1)
    session.final = make_frame()
    window._on_stop_collect_clicked()
    assert wait_until(qapp, lambda: not controller.collecting, timeout_ms=8000)

    assert window._editor.toPlainText() == "保留我"
    assert window._collect_label.text() == dw.COLLECT_EMPTY_TEXT
    window.close()
    controller.shutdown()


def test_status_snapshot_drives_badge_and_buttons(build_window):
    controller, window, _engine, _sessions = build_window()

    window._on_collection_status(
        {
            "collecting": True,
            "stopping": False,
            "session_state": "采集中",
            "frames": 4,
            "queued": 2,
            "dropped": 1,
            "lines": 7,
            "breakpoints": 1,
        }
    )
    text = window._collect_badge.text()
    assert "7 行" in text and "断点 1" in text and "队列 2" in text and "丢帧 1" in text
    assert window._collect_badge.isHidden() is False
    assert window._collect_button.isEnabled() is False
    assert window._stop_collect_button.isEnabled() is True

    # While stopping nothing may be started, but the stop button goes quiet.
    window._on_collection_status(
        {
            "collecting": False,
            "stopping": True,
            "frames": 5,
            "queued": 1,
            "dropped": 0,
            "lines": 7,
            "breakpoints": 1,
        }
    )
    assert window._collect_button.isEnabled() is False
    assert window._stop_collect_button.isEnabled() is False
    window.close()
    controller.shutdown()


def test_hint_is_mirrored_into_status_message(build_window):
    controller, window, _engine, _sessions = build_window()
    window._on_collection_hint("滚动太快，画面队列已满：请放慢滚动速度")
    assert "队列已满" in window._live_label.toolTip()
    window.close()
    controller.shutdown()


def test_copy_button_puts_text_on_clipboard(build_window):
    controller, window, _engine, _sessions = build_window(editor_text="甲：在吗\n乙：在")
    window._on_copy_text()
    clipboard = QGuiApplication.clipboard()
    assert clipboard.text() == "甲：在吗\n乙：在"
    window.close()
    controller.shutdown()


def test_export_writes_utf8_without_bom_and_lf(build_window, monkeypatch, tmp_path):
    controller, window, _engine, _sessions = build_window(
        editor_text="甲：明天几点开会\n乙：九点半"
    )
    target = tmp_path / "言外-聊天记录.txt"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "文本文件 (*.txt)")),
    )

    window._on_export_text()
    assert target.exists()
    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")          # no BOM
    assert b"\r\n" not in raw                          # LF only
    assert raw.decode("utf-8") == "甲：明天几点开会\n乙：九点半"
    assert window._last_export_path == str(target)
    window.close()
    controller.shutdown()


def test_export_is_refused_on_empty_editor(build_window, monkeypatch, tmp_path):
    controller, window, _engine, _sessions = build_window()
    calls: list[tuple] = []
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: calls.append(args) or ("", "")),
    )
    window._on_export_text()
    assert calls == []            # dialog never opened
    assert "无可导出" in window._live_label.toolTip()
    window.close()
    controller.shutdown()


def test_single_shot_entry_points_still_work_while_idle(build_window):
    controller, window, _engine, _sessions = build_window()
    window._on_read_clicked()
    assert window._pending_action == "capture"
    assert FakeSelector.instances[-1].started is True
    window._selector.cancel()
    window.close()
    controller.shutdown()


def test_read_is_refused_while_collecting(build_window, qapp):
    controller, window, _engine, sessions = build_window()
    assert controller.start_collection(REGION) is True

    window._on_read_clicked()
    window._on_reselect_clicked()
    window._on_analyze_clicked()
    # The window intercepts these before the controller, so the reason lands in
    # the status bar tooltip rather than in controller.status_message.
    assert "连续采集" in window._live_label.toolTip()
    assert window._pending_action is None

    window._on_stop_collect_clicked()
    assert wait_until(qapp, lambda: not controller.collecting, timeout_ms=5000)
    window.close()
    controller.shutdown()


def test_pause_and_resume_update_the_strip(build_window, qapp):
    controller, window, _engine, sessions = build_window()
    assert controller.start_collection(REGION) is True
    session = sessions[0]

    # CaptureSession emits state_changed("暂停") before paused(reason).
    session.state_changed.emit("暂停")
    session.paused.emit("前台窗口没有覆盖选区（可能切换了聊天窗口）")
    assert "暂停" in window._collect_label.text()
    session.resumed.emit()
    session.state_changed.emit("采集中")
    assert "采集中" in window._collect_label.text()

    window._on_stop_collect_clicked()
    assert wait_until(qapp, lambda: not controller.collecting, timeout_ms=5000)
    window.close()
    controller.shutdown()


def test_clear_resets_the_collect_strip(build_window, qapp):
    controller, window, _engine, sessions = build_window()
    assert controller.start_collection(REGION) is True
    window._on_collection_status(
        {"collecting": True, "stopping": False, "frames": 2, "queued": 0,
         "dropped": 0, "lines": 3, "breakpoints": 0}
    )
    assert window._collect_badge.isHidden() is False

    controller.clear()
    assert wait_until(qapp, lambda: not controller.collecting, timeout_ms=3000)
    assert window._collect_badge.isVisible() is False
    assert window._collect_label.text() == dw.COLLECT_IDLE_TEXT
    assert window._collect_button.isEnabled() is True
    assert window._stop_collect_button.isEnabled() is False
    window.close()
    controller.shutdown()


def test_tone_for_state_covers_collection_labels():
    assert tone_for_state("采集中") == "cyan"
    assert tone_for_state("采集暂停") == "amber"
    assert tone_for_state("收尾") == "amber"
    assert tone_for_state("已采集") == "green"
    assert tone_for_state("待机") == "gray"


def test_write_text_file_helper_is_utf8(build_window, tmp_path):
    controller, window, _engine, _sessions = build_window()
    path = tmp_path / "out.txt"
    DecoderWindow.write_text_file(str(path), "对方：好的\n我：收到")
    assert Path(path).read_bytes() == "对方：好的\n我：收到".encode("utf-8")
    window.close()
    controller.shutdown()

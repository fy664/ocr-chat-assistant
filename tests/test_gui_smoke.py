"""GUI smoke tests: main window / settings dialog / region selector can
instantiate without import errors (headless offscreen platform)."""
from __future__ import annotations

import pytest

from app.analysis.scheduler import PipelineScheduler
from app.capture.region_selector import RegionSelector
from app.llm.client import MockLLMClient
from app.ui.floating_panel import AnalysisCards, ReplyList
from app.ui.main_window import MainWindow
from app.ui.ocr_editor import OCREditor
from app.ui.settings_dialog import SettingsDialog
from app.ui.status_bar import AppStatusBar
from tests.helpers import StubOCREngine


@pytest.fixture()
def scheduler(qapp, make_settings):
    settings = make_settings()
    sched = PipelineScheduler(
        settings,
        mock_llm=True,
        ocr_engine_factory=lambda: StubOCREngine(),
    )
    yield sched
    sched.shutdown()


def test_main_window_instantiates(qapp, scheduler, make_settings):
    window = MainWindow(scheduler, make_settings())
    window.show()
    qapp.processEvents()
    assert window.windowTitle()
    assert window.isVisible()
    window.close()
    qapp.processEvents()


def test_settings_dialog_instantiates(qapp, make_settings):
    dialog = SettingsDialog(make_settings())
    assert dialog.windowTitle() == "设置"
    dialog.close()


def test_region_selector_instantiates_and_cancels(qapp):
    selector = RegionSelector()
    assert not selector.is_active
    selector.start()
    qapp.processEvents()
    assert selector.is_active
    selector.cancel()
    qapp.processEvents()
    assert not selector.is_active


def test_analysis_cards_update(qapp):
    from app.llm.client import MOCK_RESULT

    cards = AnalysisCards()
    cards.set_result(MOCK_RESULT)
    assert cards.current_result is MOCK_RESULT
    cards.set_updating(True)
    assert not cards._updating.isHidden()
    cards.clear_result()
    assert cards.current_result is None


def test_reply_list_and_copy(qapp):
    from app.llm.client import MOCK_RESULT
    from PySide6.QtWidgets import QApplication

    replies = ReplyList()
    replies.set_replies(MOCK_RESULT.suggested_replies)
    assert replies._layout.count() == 3
    copied = []
    replies.copy_requested.connect(copied.append)
    assert QApplication.clipboard() is not None
    replies.clear_replies()
    assert replies._layout.count() == 1


def test_ocr_editor_tabs(qapp):
    editor = OCREditor()
    editor.set_ocr_text("你好", "你好")
    assert editor._edit_view.toPlainText() == "你好"
    editor._edit_view.setPlainText("你好（修正）")
    editor._on_apply()
    assert editor._override_active


def test_status_bar(qapp):
    bar = AppStatusBar()
    bar.set_state("监控中")
    bar.set_ocr_busy(True)
    bar.set_llm_busy(False)
    bar.set_last_update(1700000000.0)
    assert bar._state_label.text() == "监控中"
    assert "忙碌" in bar._ocr_label.text()

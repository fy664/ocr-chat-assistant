"""v2 UI widget smoke tests: thinking panel, stage stepper, image preview."""
from __future__ import annotations

import numpy as np

from app.analysis.decoder import DecoderController
from app.config.settings import Settings
from app.ui.decoder_window import DecoderWindow
from app.ui.panels import ImagePreview, StageStepper, ThinkingPanel


def test_thinking_panel_streams_and_summarizes(qapp):
    panel = ThinkingPanel()
    panel.set_enabled(True)
    panel.begin()
    panel.append("先看证据：对方给了具体时间。\n")
    panel.append("再判断情绪：期待，置信度 0.71。")
    panel.finish(["步骤一", "步骤二"], elapsed=1.2)
    assert "已深度思考" in panel._toggle.text()
    assert "1.2s" in panel._toggle.text()
    assert "先看证据" in panel._body.toPlainText()
    panel.reset()
    assert panel._body.toPlainText() == ""


def test_thinking_panel_disabled_state(qapp):
    panel = ThinkingPanel()
    panel.set_enabled(False)
    panel.begin()
    assert "已关闭" in panel._toggle.text()
    assert panel._body.toPlainText() == ""


def test_stage_stepper_tracks_states(qapp):
    stepper = StageStepper()
    stepper.set_stage("ocr", "active")
    stepper.set_stage("ocr", "done")
    stepper.set_stage("llm", "active")
    assert stepper._states["ocr"] == "done"
    assert stepper._states["llm"] == "active"
    stepper.reset()
    assert all(state == "idle" for state in stepper._states.values())


def test_image_preview_accepts_frame_and_clear(qapp):
    preview = ImagePreview()
    preview.set_frame(np.zeros((48, 64, 3), dtype=np.uint8))
    assert preview._pixmap is not None and not preview._pixmap.isNull()
    preview.clear()
    assert preview._pixmap is None


def test_decoder_window_is_on_demand_and_named_yanwai(qapp):
    settings = Settings()
    controller = DecoderController(settings, mock_llm=True)
    window = DecoderWindow(controller, settings)
    assert "言外" in window.windowTitle()
    assert window._editor is not None
    assert window._deep_check.isChecked() is False
    assert "不会持续监控" in window._region_label.text()
    window.close()
    controller.shutdown()

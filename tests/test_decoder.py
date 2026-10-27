"""Tests for the v2 on-demand decoder (no monitoring)."""
from __future__ import annotations

import numpy as np

from app.analysis.decoder import DecoderController
from app.config.settings import Settings
from app.llm.client import MOCK_RESULT
from tests.helpers import StubOCREngine, wait_until


class RecordingClient:
    def __init__(self) -> None:
        self.calls = 0
        self.images = None
        self.system = ""
        self.user = ""

    def analyze(self, system_prompt: str, context: str, images=None):
        self.calls += 1
        self.system = system_prompt
        self.user = context
        self.images = images
        return MOCK_RESULT.model_copy(deep=True)


def _settings(**overrides) -> Settings:
    settings = Settings(
        llm_provider="custom",
        llm_api_key="test-key",
        llm_base_url="http://example.invalid/v1",
        llm_model="test-model",
        thinking_enabled=False,
        vision_enabled=True,
        long_text_max_chars=30000,
        max_screenshots=2,
        llm_max_tokens=2600,
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def test_capture_and_analyze_sends_both_text_and_image(qapp):
    settings = _settings()
    client = RecordingClient()
    ocr = StubOCREngine(["对方：你周末有空吗？\n我：怎么啦"])
    controller = DecoderController(
        settings,
        ocr_engine_factory=lambda: ocr,
        client_factory=lambda: client,
    )
    captured = []
    completed = []
    controller.capture_completed.connect(captured.append)
    controller.analysis_completed.connect(completed.append)

    controller.capture_from_image(np.full((80, 120, 3), 120, dtype=np.uint8))
    assert wait_until(qapp, lambda: captured, timeout_ms=4000)
    assert "你周末有空吗" in captured[0]
    assert controller.image_count == 1
    assert controller.images[0].startswith("data:image/jpeg;base64,")

    controller.analyze(captured[0], thinking=False)
    assert wait_until(qapp, lambda: completed, timeout_ms=4000)
    assert client.calls == 1
    assert client.images and len(client.images) == 1
    assert "【完整对话】" in client.user
    assert "【画面】" in client.user
    assert completed[0].vision_used is True
    controller.shutdown()


def test_analyze_text_only_when_vision_disabled(qapp):
    settings = _settings(vision_enabled=False)
    client = RecordingClient()
    controller = DecoderController(
        settings,
        ocr_engine_factory=lambda: StubOCREngine([]),
        client_factory=lambda: client,
    )
    completed = []
    controller.analysis_completed.connect(completed.append)
    controller.capture_from_image(np.zeros((40, 60, 3), dtype=np.uint8))
    assert wait_until(qapp, lambda: not controller.busy, timeout_ms=3000)
    controller.analyze("对方：嗯。\n我：好。", thinking=False)
    assert wait_until(qapp, lambda: completed, timeout_ms=4000)
    assert client.images is None
    assert "【画面】" not in client.user
    controller.shutdown()


def test_long_text_is_truncated_to_configured_limit(qapp):
    settings = _settings(long_text_max_chars=5000)
    client = RecordingClient()
    controller = DecoderController(
        settings,
        ocr_engine_factory=lambda: StubOCREngine([]),
        client_factory=lambda: client,
    )
    completed = []
    controller.analysis_completed.connect(completed.append)
    long_text = "甲：" + ("很长的对话" * 1200) + "\n乙：最后一句"
    controller.analyze(long_text, thinking=False)
    assert wait_until(qapp, lambda: completed, timeout_ms=4000)
    assert "保留了最近的部分" in client.user or len(client.user) < 30000
    assert "最后一句" in client.user
    controller.shutdown()


def test_clear_resets_images_and_state(qapp):
    settings = _settings()
    controller = DecoderController(
        settings,
        ocr_engine_factory=lambda: StubOCREngine(["hi"]),
        client_factory=lambda: RecordingClient(),
    )
    controller.capture_from_image(np.zeros((40, 60, 3), dtype=np.uint8))
    assert wait_until(qapp, lambda: controller.image_count == 1, timeout_ms=4000)
    cleared = []
    controller.cleared.connect(lambda: cleared.append(True))
    controller.clear()
    assert cleared and controller.image_count == 0 and controller.region is None
    controller.shutdown()

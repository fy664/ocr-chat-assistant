from __future__ import annotations

import json
import logging
from threading import Event

import numpy as np

from app.analysis.decoder import DecoderController
from app.config.settings import Settings
from app.ui.decoder_window import DecoderWindow
from app.ui.settings_dialog import SettingsDialog
from app.utils.logger import SecretRedactionFormatter, register_secret
from tests.helpers import StubOCREngine, wait_until


def test_invalid_config_field_does_not_discard_other_preferences(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    cfg, dotenv = tmp_path / "config.json", tmp_path / ".env"
    cfg.write_text(json.dumps({"llm_model": "chosen-model", "scroll_max_queue": "invalid",
                               "vision_enabled": False, "thinking_enabled": True}), encoding="utf-8")
    dotenv.write_text("LLM_MODEL=dev-model\nLLM_API_KEY=synthetic-private-value\n", encoding="utf-8")
    loaded = Settings.load(config_path=cfg, dotenv_path=dotenv, use_keyring=False)
    assert loaded.llm_model == "chosen-model"
    assert loaded.scroll_max_queue == Settings().scroll_max_queue
    assert not loaded.vision_enabled and loaded.thinking_enabled
    assert loaded.llm_api_key == "synthetic-private-value"
    assert Settings.load(config_path=cfg, dotenv_path=tmp_path / "absent", use_keyring=False).llm_api_key == ""


def test_keyring_failure_preserves_saved_settings(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"llm_model": "previous"}', encoding="utf-8")
    monkeypatch.setattr("app.config.settings._keyring_set", lambda *_: False)
    settings = Settings(llm_model="new-model", llm_api_key="synthetic-key")
    try:
        settings.save(config_path=cfg)
    except OSError:
        pass
    else:
        raise AssertionError("expected a failed credential save")
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"llm_model": "previous"}
    assert sorted(path.name for path in tmp_path.iterdir()) == ["config.json"]


def test_log_formatter_redacts_child_messages_and_tracebacks():
    key = "synthetic-value-7fd130"
    register_secret(key)
    try:
        raise RuntimeError(f"trace bearer longtokenvalue {key}")
    except RuntimeError as exc:
        record = logging.getLogger("ocr_chat.child").makeRecord(
            "ocr_chat.child", logging.WARNING, __file__, 1, "message %s %s",
            ("sk-synthetic-12345", key), (type(exc), exc, exc.__traceback__),
        )
    rendered = SecretRedactionFormatter("%(name)s %(message)s").format(record)
    assert "ocr_chat.child" in rendered and "RuntimeError" in rendered
    for secret in (key, "sk-synthetic-12345", "longtokenvalue"):
        assert secret not in rendered


def test_settings_controls_edit_current_capture_fields(qapp, make_settings):
    old = make_settings(scroll_capture_interval_ms=750, capture_interval_ms=2000)
    dialog = SettingsDialog(old)
    dialog._interval_spin.setValue(1100)
    dialog._queue_spin.setValue(9)
    dialog._on_save()
    saved = dialog.get_result()["settings"]
    assert (saved.scroll_capture_interval_ms, saved.scroll_max_queue) == (1100, 9)
    assert saved.capture_interval_ms == old.capture_interval_ms == 2000
    assert old.scroll_capture_interval_ms == 750


def test_window_close_waits_asynchronously_for_busy_ocr(qapp, make_settings):
    entered, release = Event(), Event()

    class SlowEngine(StubOCREngine):
        def recognize(self, image):
            entered.set()
            release.wait(5)
            return super().recognize(image)

    settings = make_settings(vision_enabled=False)
    controller = DecoderController(settings, mock_llm=True,
                                   ocr_engine_factory=lambda: SlowEngine(["合成聊天"]))
    window = DecoderWindow(controller, settings)
    window.show()
    try:
        controller.capture_from_image(np.zeros((24, 24, 3), dtype=np.uint8))
        assert entered.wait(1)
        assert not window.close()
        assert window.isVisible()
        assert not window.centralWidget().isEnabled()
        release.set()
        assert wait_until(qapp, lambda: not window.isVisible())
    finally:
        release.set()
        controller.shutdown()
        window.close()

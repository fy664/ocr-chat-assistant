"""Shared pytest fixtures.

Sets the offscreen Qt platform so GUI tests run headless, and provides
a session-scoped QApplication plus reusable mock components.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def temp_config_path(tmp_path) -> Path:
    return tmp_path / "config.json"


@pytest.fixture()
def make_settings(temp_config_path, monkeypatch):
    """Factory returning a Settings loaded from an isolated temp location."""
    from app.config.settings import Settings

    def _make(**overrides) -> Settings:
        monkeypatch.setattr(
            "app.config.settings._keyring_get", lambda service: ""
        )
        monkeypatch.setattr(
            "app.config.settings._keyring_set", lambda service, value: False
        )
        s = Settings.load(
            config_path=temp_config_path,
            dotenv_path=temp_config_path.parent / ".env",
            use_keyring=False,
        )
        for key, value in overrides.items():
            setattr(s, key, value)
        return s

    return _make


@pytest.fixture()
def scheduler_factory(qapp, make_settings):
    """Factory building a PipelineScheduler with stub OCR + mock LLM clients.

    - stub_texts:   list of texts the stub OCR engine returns per recognize()
    - llm_clients:  list of LLMClient instances consumed per analysis request
    - settings:     optional custom Settings
    All created schedulers are shut down after the test.
    """
    from app.analysis.scheduler import PipelineScheduler
    from tests.helpers import StubOCREngine

    created = []

    def _make(*, settings=None, stub_texts=None, llm_clients=None, **kwargs):
        s = settings or make_settings(debounce_ms=300, capture_interval_ms=500)
        llm_factory = None
        if llm_clients is not None:
            iterator = iter(llm_clients)
            llm_factory = lambda: next(iterator)
        engine_factory = lambda: StubOCREngine(texts=stub_texts)
        scheduler = PipelineScheduler(
            s,
            llm_factory=llm_factory,
            ocr_engine_factory=engine_factory,
            **kwargs,
        )
        created.append(scheduler)
        return scheduler

    yield _make

    for scheduler in created:
        scheduler.shutdown()

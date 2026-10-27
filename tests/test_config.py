"""Config tests: defaults, .env, missing key/model/base_url, clamping, roundtrip."""
from __future__ import annotations

import json
import os

from app.config.settings import Settings


def test_defaults():
    s = Settings()
    assert s.capture_interval_ms == 2000
    assert s.debounce_ms == 700
    assert s.max_context_messages == 20
    assert s.max_context_chars == 8000
    assert s.llm_temperature == 0.3
    assert s.llm_timeout == 90.0
    assert s.always_on_top is True
    assert s.auto_start_monitoring is False
    assert s.is_llm_configured is False


def test_env_file_loading(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=deepseek\n"
        "LLM_API_KEY=sk-test-1234567890\n"
        "LLM_BASE_URL=https://api.example.com/v1\n"
        "LLM_MODEL=test-model\n"
        "LLM_TEMPERATURE=0.5\n"
        "LLM_TIMEOUT=45\n",
        encoding="utf-8",
    )
    try:
        s = Settings.load(
            dotenv_path=env_file,
            config_path=tmp_path / "config.json",
            use_keyring=False,
        )
        assert s.llm_provider == "deepseek"
        assert s.llm_api_key == "sk-test-1234567890"
        assert s.llm_base_url == "https://api.example.com/v1"
        assert s.llm_model == "test-model"
        assert s.llm_temperature == 0.5
        assert s.llm_timeout == 45.0
        assert s.is_llm_configured is True
    finally:
        # load_dotenv writes into os.environ directly; pop them ourselves
        # (monkeypatch.delenv would *restore* these values at teardown,
        # leaking the test key into every later test)
        for key in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
                    "LLM_TEMPERATURE", "LLM_TIMEOUT"):
            os.environ.pop(key, None)


def test_env_overrides_config_file(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"llm_base_url": "https://from-config/v1", "llm_model": "config-model"}),
        encoding="utf-8",
    )
    os.environ["LLM_BASE_URL"] = "https://from-env/v1"
    try:
        s = Settings.load(dotenv_path=tmp_path / "nope.env", config_path=cfg, use_keyring=False)
        assert s.llm_base_url == "https://from-env/v1"  # env wins
        assert s.llm_model == "config-model"            # config used when env absent
    finally:
        os.environ.pop("LLM_BASE_URL", None)


def test_missing_key(tmp_path):
    s = Settings.load(dotenv_path=tmp_path / "nope.env", config_path=tmp_path / "c.json", use_keyring=False)
    s.llm_base_url = "https://api.example.com/v1"
    s.llm_model = "some-model"
    assert s.llm_api_key == ""
    assert s.is_llm_configured is False  # key missing


def test_missing_model(tmp_path):
    s = Settings.load(dotenv_path=tmp_path / "nope.env", config_path=tmp_path / "c.json", use_keyring=False)
    s.llm_api_key = "sk-xxx"
    s.llm_base_url = "https://api.example.com/v1"
    assert s.is_llm_configured is False  # model missing


def test_missing_base_url(tmp_path):
    s = Settings.load(dotenv_path=tmp_path / "nope.env", config_path=tmp_path / "c.json", use_keyring=False)
    s.llm_api_key = "sk-xxx"
    s.llm_model = "some-model"
    assert s.is_llm_configured is False  # base url missing


def test_clamping():
    s = Settings(capture_interval_ms=100, debounce_ms=99999, llm_temperature=9.9,
                 max_context_messages=1, max_context_chars=10)
    s.clamp()
    assert s.capture_interval_ms == 500
    assert s.debounce_ms == 1500
    assert s.llm_temperature == 2.0
    assert s.max_context_messages == 5
    assert s.max_context_chars == 1000


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings._keyring_get", lambda service: "")
    monkeypatch.setattr("app.config.settings._keyring_set", lambda service, value: True)
    cfg = tmp_path / "config.json"
    s = Settings(llm_provider="my-provider", llm_base_url="https://x/v1", llm_model="m",
                 llm_api_key="sk-secret-key-value", capture_interval_ms=1500)
    s.save(config_path=cfg, use_keyring=True)
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    assert "llm_api_key" not in raw  # never persisted to config.json
    assert raw["llm_provider"] == "my-provider"
    assert raw["capture_interval_ms"] == 1500

    loaded = Settings.load(dotenv_path=tmp_path / "nope.env", config_path=cfg, use_keyring=False)
    assert loaded.llm_provider == "my-provider"
    assert loaded.capture_interval_ms == 1500
    assert loaded.llm_api_key == ""  # without keyring the key is not in config

"""Application settings.

Storage:
  - Non-sensitive config : %APPDATA%\\OCRChatAssistant\\config.json
  - API key             : Windows Credential Manager (keyring) first,
                          .env fallback for development.
Read priority: environment variables > keyring > config.json.
The API key is never logged and never written back into config.json.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, PrivateAttr

APP_NAME = "OCRChatAssistant"
KEYRING_SERVICE = "llm_api_key"

logger = logging.getLogger("ocr_chat.settings")

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_config_path() -> Path:
    return config_dir() / "config.json"


def default_logs_dir() -> Path:
    d = config_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_dotenv_path() -> Path:
    return PROJECT_ROOT / ".env"


def _keyring_get(service: str) -> str:
    try:
        import keyring

        return keyring.get_password(APP_NAME, service) or ""
    except Exception:
        return ""


def _keyring_set(service: str, value: str) -> bool:
    try:
        import keyring

        keyring.set_password(APP_NAME, service, value)
        return True
    except Exception:
        return False


def _dotenv_write(key: str, value: str) -> None:
    """Minimal .env writer used only as a dev fallback when keyring is unavailable."""
    path = default_dotenv_path()
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class Settings(BaseModel):
    """All user-facing configuration with spec defaults."""

    # LLM
    llm_provider: str = "custom"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.3
    llm_timeout: float = 90.0

    # Realtime
    capture_interval_ms: int = 2000
    debounce_ms: int = 700
    max_context_messages: int = 20
    max_context_chars: int = 8000
    min_ocr_chars: int = 2

    # Context
    speaker_heuristic: bool = True

    # Analysis / multimodal (v2 on-demand decoder)
    thinking_enabled: bool = False      # 深度思考默认关闭：快速解读优先
    thinking_auto_collapse: bool = True
    vision_enabled: bool = True         # 按需解读默认附带画面（表情包/贴纸）
    vision_max_side: int = 1024
    vision_quality: int = 80
    fast_frame_gate: bool = True
    long_text_max_chars: int = 30000
    max_screenshots: int = 4
    llm_max_tokens: int = 2600
    vision_defaulted_v2: bool = False  # 一次性迁移标记：v2 首次启动启用按需画面理解
    fast_defaulted_v2: bool = False    # 一次性迁移标记：v2 首次启动默认快速解读

    # UI
    always_on_top: bool = True
    auto_start_monitoring: bool = False

    # Persisted last region (physical pixels)
    region: dict | None = None

    _config_path: Path | None = PrivateAttr(default=None)

    # ---- validation / clamping -------------------------------------------

    def clamp(self) -> "Settings":
        self.capture_interval_ms = max(500, min(3000, self.capture_interval_ms))
        self.debounce_ms = max(300, min(1500, self.debounce_ms))
        self.max_context_messages = max(5, min(100, self.max_context_messages))
        self.max_context_chars = max(1000, min(50000, self.max_context_chars))
        self.min_ocr_chars = max(1, min(20, self.min_ocr_chars))
        self.llm_temperature = max(0.0, min(2.0, self.llm_temperature))
        self.llm_timeout = max(5.0, min(300.0, self.llm_timeout))
        self.vision_max_side = max(384, min(1600, int(self.vision_max_side)))
        self.vision_quality = max(50, min(95, int(self.vision_quality)))
        self.long_text_max_chars = max(2000, min(100000, int(self.long_text_max_chars)))
        self.max_screenshots = max(1, min(6, int(self.max_screenshots)))
        self.llm_max_tokens = max(512, min(16000, int(self.llm_max_tokens)))
        return self

    @property
    def is_llm_configured(self) -> bool:
        return bool(self.llm_api_key and self.llm_base_url and self.llm_model)

    @property
    def stored_region(self):
        from app.models.schemas import ScreenRegion

        if not self.region:
            return None
        try:
            r = ScreenRegion.model_validate(self.region)
            return r if r.width > 0 and r.height > 0 else None
        except Exception:
            return None

    # ---- load / save ------------------------------------------------------

    @classmethod
    def load(
        cls,
        dotenv_path: Path | None = None,
        config_path: Path | None = None,
        use_keyring: bool = True,
    ) -> "Settings":
        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=dotenv_path or default_dotenv_path(), override=False)
        except Exception:
            pass

        cfg = config_path or default_config_path()
        data: dict = {}
        if cfg.exists():
            try:
                raw = json.loads(cfg.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except Exception as exc:
                logger.warning("config.json unreadable, using defaults: %s", exc)

        data.pop("llm_api_key", None)  # never trusted from config.json

        settings = cls(**{k: v for k, v in data.items() if k in cls.model_fields})
        settings._config_path = cfg

        # API key: env > keyring
        settings.llm_api_key = os.environ.get("LLM_API_KEY", "").strip()
        if not settings.llm_api_key and use_keyring:
            settings.llm_api_key = _keyring_get(KEYRING_SERVICE).strip()

        # Other LLM fields: env > config.json
        if os.environ.get("LLM_PROVIDER"):
            settings.llm_provider = os.environ["LLM_PROVIDER"].strip()
        if os.environ.get("LLM_BASE_URL"):
            settings.llm_base_url = os.environ["LLM_BASE_URL"].strip()
        if os.environ.get("LLM_MODEL"):
            settings.llm_model = os.environ["LLM_MODEL"].strip()
        if os.environ.get("LLM_TEMPERATURE"):
            try:
                settings.llm_temperature = float(os.environ["LLM_TEMPERATURE"])
            except ValueError:
                pass
        if os.environ.get("LLM_TIMEOUT"):
            try:
                settings.llm_timeout = float(os.environ["LLM_TIMEOUT"])
            except ValueError:
                pass

        return settings.clamp()

    def save(self, config_path: Path | None = None, use_keyring: bool = True) -> None:
        self.clamp()
        data = self.model_dump()
        data.pop("llm_api_key", None)
        cfg = config_path or self._config_path or default_config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        if self.llm_api_key:
            if use_keyring and _keyring_set(KEYRING_SERVICE, self.llm_api_key):
                logger.info("API key saved to Windows Credential Manager")
            else:
                _dotenv_write("LLM_API_KEY", self.llm_api_key)
                logger.warning(
                    "keyring unavailable - API key written to local .env (gitignored) as dev fallback"
                )

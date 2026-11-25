"""Application settings.

Storage:
  - Non-sensitive config : %APPDATA%\\OCRChatAssistant\\config.json
  - API key             : Windows Credential Manager (keyring) first,
                          .env fallback for development.
Process environment overrides saved settings. The developer .env supplies defaults.
The API key is never logged and never written back into config.json.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from dotenv import dotenv_values
from pydantic import BaseModel, PrivateAttr, ValidationError

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

    # Continuous scrolling capture (rebuild a transcript from many screenshots)
    scroll_capture_interval_ms: int = 700   # sampling period while the user scrolls
    scroll_max_queue: int = 6               # frames waiting for OCR before warning
    scroll_min_overlap_lines: int = 2       # overlap needed to trust a merge
    scroll_match_threshold: float = 0.70    # per-line similarity for a match

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
        self.scroll_capture_interval_ms = max(
            300, min(2000, int(self.scroll_capture_interval_ms))
        )
        self.scroll_max_queue = max(2, min(16, int(self.scroll_max_queue)))
        self.scroll_min_overlap_lines = max(1, min(5, int(self.scroll_min_overlap_lines)))
        self.scroll_match_threshold = max(0.5, min(0.95, float(self.scroll_match_threshold)))
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
            defaults = dotenv_values(dotenv_path or default_dotenv_path(), encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            logger.warning("developer .env unreadable (%s)", type(exc).__name__)
            defaults = {}
        cfg = config_path or default_config_path()
        data: dict = {}
        try:
            raw = json.loads(cfg.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                data = {name: value for name, value in raw.items()
                        if name in cls.model_fields and name != "llm_api_key"}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            logger.warning("config.json unreadable (%s), using defaults", type(exc).__name__)

        settings = cls._validate_saved_fields(data)
        settings._config_path = cfg
        process_key = os.environ.get("LLM_API_KEY", "").strip()
        saved_key = _keyring_get(KEYRING_SERVICE).strip() if use_keyring and not process_key else ""
        settings.llm_api_key = process_key or saved_key or (defaults.get("LLM_API_KEY") or "").strip()

        for field in ("llm_provider", "llm_base_url", "llm_model", "llm_temperature", "llm_timeout"):
            name = field.upper()
            value = os.environ.get(name)
            if not value and field not in data:
                value = defaults.get(name)
            if value:
                try:
                    current = getattr(settings, field)
                    setattr(settings, field, type(current)(value.strip()))
                except ValueError:
                    logger.warning("invalid value for %s, retaining configured value", name)
        return settings.clamp()

    @classmethod
    def _validate_saved_fields(cls, data: dict) -> "Settings":
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            invalid = {error["loc"][0] for error in exc.errors(include_input=False)}
            logger.warning("ignoring invalid settings fields: %s", ", ".join(sorted(invalid)))
            for field in invalid:
                data.pop(field, None)
            return cls.model_validate(data)

    def save(
        self, config_path: Path | None = None, use_keyring: bool = True, *, write_api_key: bool = True,
    ) -> None:
        self.clamp()
        data = self.model_dump(exclude={"llm_api_key"})
        cfg = config_path or self._config_path or default_config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile("w", dir=cfg.parent, prefix=".config-", suffix=".tmp",
                                    encoding="utf-8", delete=False) as file:
                temporary = Path(file.name)
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
            if write_api_key and use_keyring and self.llm_api_key:
                if not _keyring_set(KEYRING_SERVICE, self.llm_api_key):
                    raise OSError("无法访问 Windows 凭据管理器，API Key 未保存。")
            temporary.replace(cfg)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

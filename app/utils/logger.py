"""Logging setup with secret redaction.

Log file: %APPDATA%\\OCRChatAssistant\\logs\\app.log
Never logged: API keys, full chat content, screenshot data.
"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{8,}"),
    re.compile(r"(?i)(api[_-]?key[\"'=:\s]+)[A-Za-z0-9_\-\.]{8,}"),
]

_extra_secrets: list[str] = []


def register_secret(value: str) -> None:
    if value and value not in _extra_secrets:
        _extra_secrets.append(value)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            for pattern in _SECRET_PATTERNS:
                msg = pattern.sub(r"\1***REDACTED***", msg)
            for secret in _extra_secrets:
                msg = msg.replace(secret, "***REDACTED***")
            record.msg = msg
            record.args = ()
        except Exception:
            pass
        return True


def setup_logging(debug: bool = False, secrets: list[str] | None = None) -> logging.Logger:
    from app.config.settings import default_logs_dir

    for secret in secrets or []:
        register_secret(secret)

    logger = logging.getLogger("ocr_chat")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    try:
        file_handler = RotatingFileHandler(
            default_logs_dir() / "app.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        logger.addHandler(file_handler)
    except Exception:
        pass

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(logging.DEBUG if debug else logging.WARNING)
    logger.addHandler(console)

    logger.addFilter(SecretRedactionFilter())
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ocr_chat.{name}")

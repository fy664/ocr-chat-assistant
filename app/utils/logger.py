"""Logging setup with secret redaction.

Log file: %APPDATA%\\OCRChatAssistant\\logs\\app.log
Never logged: API keys, full chat content, screenshot data.
"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

_SECRET_PATTERNS = (
    (re.compile(r"sk-[A-Za-z0-9_-]{6,}"), "***REDACTED***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_.-]{8,}"), r"\1***REDACTED***"),
    (re.compile(r"""(?i)(api[_-]?key["'=:\s]+)[A-Za-z0-9_.-]{8,}"""), r"\1***REDACTED***"),
)

_extra_secrets: set[str] = set()


def register_secret(value: str) -> None:
    if value:
        _extra_secrets.add(value)


class SecretRedactionFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for secret in sorted(_extra_secrets.copy(), key=len, reverse=True):
            message = message.replace(secret, "***REDACTED***")
        for pattern, replacement in _SECRET_PATTERNS:
            message = pattern.sub(replacement, message)
        return message


def setup_logging(debug: bool = False, secrets: list[str] | None = None) -> logging.Logger:
    from app.config.settings import default_logs_dir

    for secret in secrets or []:
        register_secret(secret)

    logger = logging.getLogger("ocr_chat")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    formatter = SecretRedactionFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    try:
        file_handler = RotatingFileHandler(
            default_logs_dir() / "app.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.DEBUG if debug else logging.WARNING)
    logger.addHandler(console)
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ocr_chat.{name}")

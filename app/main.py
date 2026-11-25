"""言外 · 对话解码器 — application entry.

On-demand: the GUI opens immediately, OCR loads only when the user reads a
screen, and no network request happens until the user asks for a decode.
"""
from __future__ import annotations

import argparse
import logging
import sys

from app import __version__

logger = logging.getLogger("ocr_chat.main")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="言外",
        description="言外 · 读懂言外之意的对话解码器（按需读取，不持续监控）",
    )
    parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="演示模式：使用内置 Mock LLM，不调用真实 API（无需 API Key）",
    )
    parser.add_argument("--debug", action="store_true", help="启用调试日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    from app.config.settings import Settings
    from app.utils.logger import setup_logging

    settings = Settings.load()
    setup_logging(debug=args.debug, secrets=[settings.llm_api_key])
    logger.info("application startup (yanwai %s, mock_llm=%s)", __version__, args.mock_llm)
    logger.info(
        "llm configured=%s provider=%s model=%s",
        settings.is_llm_configured,
        settings.llm_provider,
        settings.llm_model or "-",
    )

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    qt_args = [sys.argv[0]]  # do not forward our CLI flags to Qt
    app = QApplication(qt_args)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    # Keep the internal name for config/keyring compatibility; the visible
    # product name is 言外.
    app.setApplicationName("OCRChatAssistant")
    app.setApplicationDisplayName("言外 · 对话解码器")

    from app.analysis.decoder import DecoderController
    from app.ui.decoder_window import DecoderWindow
    from app.ui.styles import APP_QSS
    from app.ui.widgets import app_icon

    app.setStyleSheet(APP_QSS)
    try:
        app.setWindowIcon(app_icon())
    except Exception:
        logger.debug("application icon unavailable", exc_info=True)

    controller = DecoderController(settings, mock_llm=args.mock_llm)
    window = DecoderWindow(controller, settings)
    window.show()

    exit_code = app.exec()
    controller.shutdown()
    logger.info("application exit (%s)", exit_code)
    return exit_code

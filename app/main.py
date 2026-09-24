"""Application entry: config -> logger -> Qt -> workers -> main window.

The GUI opens immediately; the PaddleOCR model loads on a background
thread (status: "正在加载 OCR 模型…"). A missing API key does not block
startup - OCR/editing work without it, only AI analysis is unavailable.
"""
from __future__ import annotations

import argparse
import logging
import sys

logger = logging.getLogger("ocr_chat.main")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="OCR Chat Assistant", description="Windows 实时聊天语义分析助手")
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
    logger.info("application startup (version 1.0.0, mock_llm=%s)", args.mock_llm)
    logger.info("llm configured=%s provider=%s model=%s",
                settings.is_llm_configured, settings.llm_provider, settings.llm_model or "-")

    from PySide6.QtWidgets import QApplication

    qt_args = [sys.argv[0]]  # do not forward our CLI flags to Qt
    app = QApplication(qt_args)
    app.setApplicationName("OCRChatAssistant")
    app.setApplicationDisplayName("OCR Chat Assistant")

    from app.analysis.scheduler import PipelineScheduler
    from app.ui.main_window import MainWindow
    from app.ui.styles import APP_QSS

    app.setStyleSheet(APP_QSS)

    scheduler = PipelineScheduler(settings, mock_llm=args.mock_llm)
    window = MainWindow(scheduler, settings)
    window.show()

    if settings.auto_start_monitoring and settings.stored_region is not None:
        scheduler.start_monitoring()

    exit_code = app.exec()
    scheduler.shutdown()
    logger.info("application exit (%s)", exit_code)
    return exit_code

"""言外 Yanwai - Windows on-demand conversation decoder entry point.

Usage:
    python run.py               # normal start
    python run.py --mock-llm    # demo mode with the built-in Mock LLM (no API key needed)
    python run.py --debug       # verbose logging
"""
from __future__ import annotations

import sys


def _check_python() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11+ is required (current: %s)" % sys.version.split()[0])


if __name__ == "__main__":
    _check_python()
    from app.main import main

    raise SystemExit(main())

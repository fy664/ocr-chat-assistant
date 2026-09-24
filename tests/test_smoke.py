"""OCR smoke tests: PaddleOCR import, engine creation, recognition on a
generated image. No real user screenshots are involved.

Note: the first run downloads PaddleOCR models (~20MB) and can take a while.
"""
from __future__ import annotations

import pytest

from app.ocr.engine import PaddleOCREngine
from app.ocr.normalize import normalize_text
from app.ocr.preprocess import preprocess


def test_paddle_imports():
    from app.ocr.engine import _patch_six_meta_path_importer

    _patch_six_meta_path_importer()  # six/PySide6 + Python 3.12 repr bug workaround
    import paddle
    import paddleocr

    assert paddle.__version__
    assert paddleocr.__version__


def test_preprocess_rgb():
    import numpy as np

    arr = np.zeros((50, 80, 3), dtype=np.uint8)
    out = preprocess(arr)
    assert out.shape == (50, 80, 3)
    assert out.dtype == np.uint8


def test_preprocess_rgba_and_gray():
    import numpy as np

    rgba = np.zeros((30, 60, 4), dtype=np.uint8)
    assert preprocess(rgba).shape == (30, 60, 3)
    gray = np.zeros((30, 60), dtype=np.uint8)
    assert preprocess(gray).shape == (30, 60, 3)


def test_paddle_ocr_recognizes_generated_image():
    """Generate 'Hello OCR 123' and require at least one token to be found."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (460, 100), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    draw.text((24, 28), "Hello OCR 123", fill="black", font=font)

    engine = PaddleOCREngine()
    assert engine.ready

    result = engine.recognize(np.asarray(image))
    assert result.raw_text.strip(), "OCR returned no text"
    joined = normalize_text(result.raw_text).upper().replace(" ", "")
    assert ("HELLO" in joined) or ("OCR" in joined) or ("123" in joined), (
        f"expected at least one of Hello/OCR/123 in: {result.raw_text!r}"
    )

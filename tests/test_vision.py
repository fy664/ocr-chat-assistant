"""Tests for the multimodal vision helpers."""
from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

from app.llm.vision import encode_image_data_url


def test_encode_image_data_url_downscales_and_uses_jpeg():
    image = np.zeros((600, 900, 3), dtype=np.uint8)
    image[:, :, 0] = 42
    url = encode_image_data_url(image, max_side=320, quality=70)
    assert url is not None
    prefix, payload = url.split(",", 1)
    assert prefix == "data:image/jpeg;base64"
    decoded = base64.b64decode(payload)
    with Image.open(io.BytesIO(decoded)) as pil:
        assert pil.format == "JPEG"
        assert max(pil.size) <= 320
        assert pil.size[0] > 0 and pil.size[1] > 0


def test_encode_missing_frame_returns_none():
    assert encode_image_data_url(None) is None
    assert encode_image_data_url(np.zeros((0, 0, 3), dtype=np.uint8)) is None


def test_encode_accepts_grayscale_frames():
    image = np.full((40, 60), 128, dtype=np.uint8)
    url = encode_image_data_url(image, max_side=128, quality=60)
    assert url is not None and url.startswith("data:image/jpeg;base64,")

"""Lightweight image preprocessing before OCR.

V1 keeps this simple: RGB conversion, optional downscale for extreme
region sizes, optional grayscale. PaddleOCR does its own internal
preprocessing; this layer only normalizes what we feed it.
"""
from __future__ import annotations

import numpy as np

MAX_SIDE = 2000


def preprocess(
    image: np.ndarray,
    max_side: int = MAX_SIDE,
    grayscale: bool = False,
) -> np.ndarray:
    if image is None:
        raise ValueError("image is None")

    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    elif arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[:, :, :3]
    elif arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"unsupported image shape {arr.shape}")

    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)

    h, w = arr.shape[:2]
    longest = max(h, w)
    if max_side > 0 and longest > max_side:
        scale = max_side / longest
        from PIL import Image

        img = Image.fromarray(arr)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        arr = np.asarray(img, dtype=np.uint8)

    if grayscale and arr.ndim == 3:
        arr = np.dot(arr[..., :3], [0.299, 0.587, 0.114]).astype(np.uint8)

    return np.ascontiguousarray(arr)

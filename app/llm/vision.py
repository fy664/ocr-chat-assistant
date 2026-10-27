"""Multimodal helpers: turn an in-memory RGB frame into a compact data URL.

Screenshots are still never written to disk. When the user explicitly enables
vision analysis, the frame is downscaled, JPEG-encoded and embedded into the
LLM request; otherwise this module is never called.
"""
from __future__ import annotations

import base64
import io
import logging

logger = logging.getLogger("ocr_chat.vision")


def encode_image_data_url(
    image,
    max_side: int = 1024,
    quality: int = 80,
) -> str | None:
    """Encode a numpy RGB frame as ``data:image/jpeg;base64,...``.

    Returns None when the frame is missing or cannot be encoded; callers should
    then fall back to a text-only request instead of failing the analysis.
    """
    if image is None:
        return None
    try:
        import numpy as np
        from PIL import Image

        array = np.asarray(image)
        if array.ndim == 3 and array.shape[2] >= 3:
            array = array[:, :, :3]
        elif array.ndim == 2:
            array = np.stack([array, array, array], axis=-1)
        else:
            return None
        if array.size == 0:
            return None

        pil = Image.fromarray(array.astype("uint8", copy=False), mode="RGB")
        side = max(128, min(1600, int(max_side)))
        if max(pil.size) > side:
            pil.thumbnail((side, side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        pil.save(
            buffer,
            format="JPEG",
            quality=max(40, min(95, int(quality))),
            optimize=True,
        )
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        logger.warning("failed to encode screenshot for vision", exc_info=True)
        return None

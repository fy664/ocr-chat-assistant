"""Fast frame gate: skip OCR when the screen is pixel-identical.

The capture loop samples every ~2s. Most samples are completely unchanged, so
hashing the raw frame (a few milliseconds) can skip a much more expensive OCR
pass. The gate is conservative: only *exact* duplicates are skipped, and after
a small number of consecutive skips it forces a full OCR pass to re-sync.
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger("ocr_chat.frame_gate")


class FrameGate:
    def __init__(self, max_skips: int = 3) -> None:
        self._last_digest: bytes | None = None
        self._consecutive_skips = 0
        self._max_skips = max(0, int(max_skips))
        self.skipped = 0
        self.processed = 0

    def is_duplicate(self, image) -> bool:
        """True when this frame can safely skip OCR."""
        if image is None:
            self._last_digest = None
            self._consecutive_skips = 0
            return False
        try:
            import numpy as np

            array = np.ascontiguousarray(image)
            if array.size == 0:
                return False
            digest = hashlib.blake2b(array, digest_size=16).digest()
        except Exception:
            logger.debug("frame hash failed; processing frame", exc_info=True)
            return False

        if digest == self._last_digest and self._consecutive_skips < self._max_skips:
            self._consecutive_skips += 1
            self.skipped += 1
            return True

        self._last_digest = digest
        self._consecutive_skips = 0
        self.processed += 1
        return False

    def reset(self) -> None:
        self._last_digest = None
        self._consecutive_skips = 0

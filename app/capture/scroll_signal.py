"""Estimate the vertical scroll direction between two region screenshots.

The stitcher works on text, and text alone cannot tell whether a new page is
*above* or *below* what is already read (the screenshot is always region
relative: the first visible line is row 0 no matter where the chat scrolled).
This module supplies that missing bit of information from pixels.

Method: reduce each frame to a grayscale row-mean profile, then cross-correlate
the current profile against the previous one over every plausible shift. The
shift that maximises the correlation is the content displacement in pixels:

* negative  -> the content moved **up**   (the user scrolled down: new messages)
* positive  -> the content moved **down** (the user scrolled up: older history)

The overlap statistics are computed in NumPy in one pass over the
candidate shifts to keep the GUI thread responsive.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger("ocr_chat.scroll_signal")


@dataclass(frozen=True)
class ShiftEstimate:
    """Content displacement between two consecutive frames."""

    shift_px: float   # positive = content moved down (scrolling up)
    score: float      # normalised correlation of the winning lag (0..1)
    direction: int    # +1 = scrolled down (new messages), -1 = scrolled up
    #: ``False`` when the profile match was too weak to trust: the frame is
    #: either unchanged or a completely different screen (a big jump). The
    #: caller must not treat those two as the same thing.
    reliable: bool = True

    @property
    def is_static(self) -> bool:
        return self.direction == 0

    @property
    def is_unknown(self) -> bool:
        """No scroll, but no proof of it either - likely a jump or a scene cut."""
        return self.direction == 0 and not self.reliable


class VerticalShiftEstimator:
    """Rolling estimator: ``update()`` per frame, remembering the previous one."""

    def __init__(
        self,
        *,
        downscale: int = 1,
        min_pixels: float = 2.0,
        min_score: float = 0.55,
        min_pixel_delta: float = 2.0,
    ) -> None:
        # Vertical resolution is kept at native pixels: a chat line pitch is
        # often an odd number, and a 4x downscale would quantise a 22px scroll
        # to a half-line and lose the correlation peak. The profile itself is
        # a row mean, so the cost stays linear in the number of pixels.
        self._downscale = max(1, int(downscale))
        self._min_pixels = float(min_pixels)
        self._min_score = float(min_score)
        #: Mean absolute profile delta below which two frames are "the same
        #: screen with noise" (caret blink, hover colour) rather than a jump.
        self._min_pixel_delta = float(min_pixel_delta)
        self._prev: np.ndarray | None = None

    def reset(self) -> None:
        self._prev = None

    # ---- profiles ---------------------------------------------------------

    def _profile(self, image) -> np.ndarray | None:
        """Grayscale row-mean profile, downscaled vertically."""
        if image is None:
            return None
        arr = np.asarray(image)
        if arr.ndim not in (2, 3) or arr.shape[0] < 4 * self._downscale:
            return None
        if arr.ndim == 3:
            arr = arr[..., :3]
        rows = arr.shape[0] // self._downscale
        # Average channels, columns and vertical groups together. This avoids
        # materializing a full-resolution grayscale or floating-point image.
        return arr[: rows * self._downscale].reshape(rows, -1).mean(axis=1, dtype=np.float64)

    @staticmethod
    def _best_shift(prev: np.ndarray, profile: np.ndarray) -> tuple[int, float]:
        """Pearson correlation for all overlaps, with an independent mean per overlap."""
        rows = len(profile)
        distances = np.arange(1, rows // 3 + 1)
        lags = np.column_stack((distances, -distances)).ravel()
        size = rows - np.abs(lags)
        prev_start = np.maximum(-lags, 0)
        curr_start = np.maximum(lags, 0)

        # Centering first limits cancellation for nearly uniform backgrounds.
        prev = prev - prev.mean()
        profile = profile - profile.mean()
        prev_sum = np.r_[0.0, np.cumsum(prev)]
        curr_sum = np.r_[0.0, np.cumsum(profile)]
        prev_squares = np.r_[0.0, np.cumsum(prev * prev)]
        curr_squares = np.r_[0.0, np.cumsum(profile * profile)]
        a = prev_sum[prev_start + size] - prev_sum[prev_start]
        b = curr_sum[curr_start + size] - curr_sum[curr_start]
        a_energy = prev_squares[prev_start + size] - prev_squares[prev_start] - a * a / size
        b_energy = curr_squares[curr_start + size] - curr_squares[curr_start] - b * b / size
        scale = np.sqrt(np.maximum(0, a_energy) * np.maximum(0, b_energy))
        products = np.correlate(profile, prev, mode="full")[rows - 1 + lags]
        scores = np.divide(products - a * b / size, scale, out=np.zeros_like(scale), where=scale > 1e-6)
        # Prefer the smaller displacement when periodic rows tie within roundoff.
        winner = np.flatnonzero(scores >= scores.max() - 1e-12)[0]
        return int(lags[winner]), float(np.clip(scores[winner], -1.0, 1.0))

    # ---- public API -------------------------------------------------------

    def update(self, image) -> ShiftEstimate | None:
        """Feed the next frame. Returns None for the very first frame."""
        profile = self._profile(image)
        if profile is None:
            return None
        prev, self._prev = self._prev, profile
        if prev is None or prev.shape != profile.shape:
            return None

        best_lag, best_score = self._best_shift(prev, profile)
        shift_px = float(best_lag * self._downscale)
        if best_score < self._min_score:
            # Weak match. Two very different causes: the screen barely changed
            # (caret blink, hover highlight) or it changed completely (jump to
            # a distant chat area). Skipping the second one loses a whole
            # screen, so tell them apart by the raw pixel delta.
            delta = float(np.abs(prev - profile).mean())
            if delta <= self._min_pixel_delta:
                logger.debug("scroll: unchanged screen (delta %.2f), shift %+.1fpx", delta, shift_px)
                return ShiftEstimate(shift_px=0.0, score=max(0.0, best_score), direction=0)
            logger.debug(
                "scroll: scene changed (delta %.1f, score %.2f): direction unknown", delta, best_score
            )
            return ShiftEstimate(
                shift_px=shift_px,
                score=max(0.0, best_score),
                direction=0,
                reliable=False,
            )
        if abs(shift_px) < self._min_pixels:
            return ShiftEstimate(shift_px=shift_px, score=best_score, direction=0)
        direction = -1 if shift_px > 0 else 1
        logger.debug(
            "scroll: shift %+.1fpx score %.2f -> direction %+d", shift_px, best_score, direction
        )
        return ShiftEstimate(shift_px=shift_px, score=best_score, direction=direction)

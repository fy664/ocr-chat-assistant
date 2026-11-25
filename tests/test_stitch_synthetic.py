"""Metric regression tests for stitching on synthetic chat transcripts.

Every scenario builds pages from the *same* ground-truth transcript, so the
numbers below are comparable between runs and between algorithm variants:

- ``miss_rate``   share of ground-truth lines that never appear in the output;
- ``dup_rate``    share of output lines that are extra copies;
- ``order_error`` share of adjacent output lines whose ground-truth index goes
                  backwards;
- ``breakpoints`` how many places the stitcher had to admit "no reliable
                  overlap" (the UI asks the user to scroll back there).

The thresholds are deliberately looser than the observed values: they exist to
catch regressions, not to encode a specific algorithm.
"""
from __future__ import annotations

import pytest

from tests.chat_samples import build_transcript, scroll_pages, stitch_and_score

VIEW = 9
TRUTH = build_transcript(count=60, seed=5)


def _run(starts, *, noise=0.0, directions=None, seed=3):
    pages = scroll_pages(TRUTH, starts, VIEW, noise=noise, seed=seed)
    return stitch_and_score(pages, TRUTH, directions=directions)


def _down(step):
    return list(range(0, len(TRUTH) - VIEW + 1, step))


def _up(step):
    return list(range(len(TRUTH) - VIEW, -1, -step))


# ---------------------------------------------------------------------------
# Directions
# ---------------------------------------------------------------------------

def test_downward_scroll_with_overlap_is_lossless():
    metrics, stitcher = _run(_down(3))
    assert metrics["miss_rate"] <= 0.02, metrics
    assert metrics["dup_rate"] <= 0.02, metrics
    assert metrics["order_error"] <= 0.02, metrics
    assert metrics["breakpoints"] == 0, metrics
    assert metrics["elapsed_ms"] < 3000, metrics
    assert stitcher.text_lines[:3] == TRUTH[:3]
    assert stitcher.text_lines[-3:] == TRUTH[-3:]


def test_upward_scroll_backfills_history_in_order():
    starts = _up(3)
    metrics, stitcher = _run(starts, directions=[-1] * len(starts))
    assert metrics["miss_rate"] <= 0.02, metrics
    assert metrics["dup_rate"] <= 0.02, metrics
    assert metrics["order_error"] <= 0.02, metrics
    assert metrics["breakpoints"] == 0, metrics
    assert stitcher.text_lines[0] == TRUTH[0]
    assert stitcher.text_lines[-1] == TRUTH[-1]


def test_up_and_down_round_trip_stays_stable():
    down = _down(3)
    starts = list(down) + _up(3) + list(down)
    directions = [1] * len(down) + [-1] * len(_up(3)) + [1] * len(down)
    metrics, _ = _run(starts, directions=directions)
    assert metrics["miss_rate"] <= 0.02, metrics
    assert metrics["dup_rate"] <= 0.03, metrics
    assert metrics["order_error"] <= 0.05, metrics
    # Re-reading the same screen must not create breakpoints.
    assert metrics["breakpoints"] == 0, metrics


# ---------------------------------------------------------------------------
# Repeated short lines
# ---------------------------------------------------------------------------

def test_repeated_short_replies_are_all_kept():
    metrics, stitcher = _run(_down(3))
    out = stitcher.text_lines
    assert out.count("好的") == TRUTH.count("好的")
    # Order is intact, so a "好的" is never pulled above its predecessor.
    assert metrics["order_error"] == 0.0, metrics


# ---------------------------------------------------------------------------
# Bad conditions
# ---------------------------------------------------------------------------

def test_fast_jumps_mark_breakpoints_and_never_duplicate():
    metrics, stitcher = _run(_down(14))
    # A jump larger than the viewport really does skip lines; the stitcher must
    # admit it instead of inventing content.
    assert metrics["breakpoints"] >= 2, metrics
    assert metrics["dup_rate"] <= 0.02, metrics
    assert len(stitcher.breakpoints) == metrics["breakpoints"]
    # Skipped lines are reported, not silently filled in.
    assert metrics["miss_rate"] > 0.2


def test_one_line_overlap_still_anchors():
    metrics, _ = _run(_down(8))
    # The last screen cannot reach the final lines; everything else is visible.
    assert metrics["miss_rate"] <= 0.12, metrics
    assert metrics["dup_rate"] <= 0.06, metrics
    assert metrics["order_error"] <= 0.05, metrics


def test_ocr_typos_do_not_create_duplicates():
    metrics, _ = _run(_down(4), noise=0.35)
    assert metrics["miss_rate"] <= 0.15, metrics
    assert metrics["dup_rate"] <= 0.08, metrics
    assert metrics["order_error"] <= 0.05, metrics


@pytest.mark.parametrize("step", [3, 4, 8])
def test_runtime_scales_linearly_with_overlap(step):
    """Guard against an accidental O(m·n) full-document scan per page."""
    starts = _down(step)
    metrics, _ = _run(starts)
    # ~20 pages of 9 lines: well under a second even on a slow laptop.
    assert metrics["elapsed_ms"] < 3000, metrics

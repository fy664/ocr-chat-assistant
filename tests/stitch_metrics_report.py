"""Printable metric report for the stitching module (阶段 4 的量化证据).

Run with::

    .venv\\Scripts\\python.exe -m tests.stitch_metrics_report

It builds one ground-truth transcript (``tests.chat_samples.build_transcript``)
and replays seven scrolling scenarios through the real
``TranscriptStitcher``. Output is a markdown table, so the numbers can be pasted
straight into the thesis' evaluation chapter.

Metrics per scenario:

- 漏行率 ``miss_rate``   — ground-truth lines never reconstructed;
- 重复行率 ``dup_rate``  — reconstructed lines that are extra copies;
- 顺序错误率 ``order_error`` — adjacent output lines whose truth index goes back;
- 断点 ``breakpoints``   — places flagged "no reliable overlap";
- 耗时 ``elapsed_ms``    — pure stitching time (OCR excluded).
"""
from __future__ import annotations

import sys

from tests.chat_samples import (
    PITCH,
    build_transcript,
    scroll_pages,
    stitch_and_score,
)

VIEW = 9
TRUTH = build_transcript(count=60, seed=5)


def _starts_down(step: int) -> list[int]:
    """Scroll downward: newest screen first, then further down."""
    return list(range(0, len(TRUTH) - VIEW + 1, step))


def _starts_up(step: int) -> list[int]:
    """Scroll upward: oldest visible screen first, then back into history."""
    return list(range(len(TRUTH) - VIEW, -1, -step))


def run_scenarios() -> list[dict]:
    rows: list[dict] = []

    def add(name: str, pages, directions=None, note: str = "") -> None:
        metrics, stitcher = stitch_and_score(pages, TRUTH, directions=directions)
        rows.append(
            {
                "name": name,
                "pages": metrics["pages"],
                "miss": metrics["miss_rate"],
                "dup": metrics["dup_rate"],
                "order": metrics["order_error"],
                "breaks": metrics["breakpoints"],
                "ms": metrics["elapsed_ms"],
                "hao": stitcher.text_lines.count("好的"),
                "note": note,
            }
        )

    add("正向 step3", scroll_pages(TRUTH, _starts_down(3), VIEW, seed=3),
        note="重叠 6 行，理想路径")
    add("正向 step4", scroll_pages(TRUTH, _starts_down(4), VIEW, seed=3),
        note="重叠 5 行")
    up = _starts_up(3)
    add("反向 step3", scroll_pages(TRUTH, up, VIEW, seed=3),
        directions=[-1] * len(up), note="向上补历史")
    down = _starts_down(3)
    round_trip = list(down) + _starts_up(3) + list(down)
    directions = [1] * len(down) + [-1] * len(_starts_up(3)) + [1] * len(down)
    add("来回 step3", scroll_pages(TRUTH, round_trip, VIEW, seed=3),
        directions=directions, note="滚回已读区域")
    add("单行重叠 step8", scroll_pages(TRUTH, _starts_down(8), VIEW, seed=3),
        note="最小可用重叠")
    add("OCR 错字 0.35", scroll_pages(TRUTH, _starts_down(4), VIEW, noise=0.35, seed=3),
        note="单字符替换")
    add("快速跳页 step14", scroll_pages(TRUTH, _starts_down(14), VIEW, seed=3),
        note="无重叠，必须报断点")
    return rows


def main() -> int:
    rows = run_scenarios()
    truth_hao = TRUTH.count("好的")
    print(f"真值 {len(TRUTH)} 行 · 视口 {VIEW} 行 · 行距 {PITCH:.0f}px · 「好的」{truth_hao} 条\n")
    print("| 场景 | 页数 | 漏行率 | 重复行率 | 顺序错误率 | 断点 | 耗时(ms) | 「好的」 | 说明 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print(
            f"| {row['name']} | {row['pages']} | {row['miss']:.3f} | "
            f"{row['dup']:.3f} | {row['order']:.3f} | {row['breaks']} | "
            f"{row['ms']:.1f} | {row['hao']}/{truth_hao} | {row['note']} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Unit tests for the scrolling-transcript stitcher.

These tests use hand-written pages with exact coordinates, so they pin down the
algorithm's decisions (which line is new, which is a repeated copy, where a
breakpoint belongs) without any OCR dependency.
"""
from __future__ import annotations

from app.analysis.stitch import (
    TranscriptStitcher,
    line_similarity,
    make_page_line,
    match_key,
    page_lines_from_ocr,
    stitch_pages,
)
from app.models.schemas import OCRLine, OCRResult
from app.utils.time import now_ts
from tests.chat_samples import build_transcript

PITCH = 22.0        # line pitch in pixels, like a chat bubble at 100% zoom
LINE_H = 18.0


def make_page(lines, *, y0=0.0, pitch=PITCH, x=10.0, confidence=0.9):
    """Build page lines with synthetic OCR boxes on a regular vertical grid."""
    page = []
    for i, text in enumerate(lines):
        top = y0 + i * pitch
        box = [
            [x, top],
            [x + 280.0, top],
            [x + 280.0, top + LINE_H],
            [x, top + LINE_H],
        ]
        pl = make_page_line(text, confidence=confidence, box=box)
        assert pl is not None
        page.append(pl)
    return page


def texts(stitcher) -> list[str]:
    return stitcher.text_lines


# ---------------------------------------------------------------------------
# Basic directions
# ---------------------------------------------------------------------------

def test_first_page_becomes_document():
    stitcher = TranscriptStitcher()
    report = stitcher.add_page(make_page(["甲：在吗", "乙：在", "甲：帮我看看这个"]))
    assert report.kind == "initial"
    assert texts(stitcher) == ["甲：在吗", "乙：在", "甲：帮我看看这个"]
    assert stitcher.text() == "\n".join(texts(stitcher))
    assert not stitcher.breakpoints


def test_downward_scroll_appends_only_new_lines():
    stitcher = TranscriptStitcher()
    stitcher.add_page(
        make_page(["甲：明天几点开会", "乙：九点半", "甲：会议室在二楼", "乙：知道了", "甲：别迟到"])
    )
    report = stitcher.add_page(
        make_page(["甲：会议室在二楼", "乙：知道了", "甲：别迟到", "乙：好的", "甲：那我先走"])
    )
    assert report.kind == "merged"
    assert report.inserted_after == 2
    assert report.inserted_before == 0
    assert texts(stitcher)[-2:] == ["乙：好的", "甲：那我先走"]
    assert len(texts(stitcher)) == 7


def test_upward_scroll_prepends_history():
    stitcher = TranscriptStitcher()
    stitcher.add_page(
        make_page(["甲：会议室在二楼", "乙：知道了", "甲：别迟到", "乙：好的", "甲：那我先走"])
    )
    report = stitcher.add_page(
        make_page(["甲：明天几点开会", "乙：九点半", "甲：会议室在二楼", "乙：知道了", "甲：别迟到"]),
        direction=-1,
    )
    assert report.kind == "merged"
    assert report.inserted_before == 2
    assert texts(stitcher)[:2] == ["甲：明天几点开会", "乙：九点半"]
    assert len(texts(stitcher)) == 7


def test_scrolling_back_to_read_area_is_a_noop():
    stitcher = TranscriptStitcher()
    stitcher.add_page(
        make_page(["甲：明天几点开会", "乙：九点半", "甲：会议室在二楼", "乙：知道了"])
    )
    before = texts(stitcher)
    report = stitcher.add_page(make_page(["甲：会议室在二楼", "乙：知道了"]), direction=-1)
    assert report.kind == "noop"
    assert report.inserted_before == report.inserted_after == 0
    assert texts(stitcher) == before
    assert not stitcher.breakpoints


def test_same_page_twice_is_a_noop():
    stitcher = TranscriptStitcher()
    page = make_page(["甲：今晚有空吗", "乙：有啊", "甲：那看电影"])
    stitcher.add_page(page)
    report = stitcher.add_page(page)
    assert report.kind == "noop"
    assert len(texts(stitcher)) == 3


def test_up_then_down_round_trip_does_not_duplicate():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["甲：记得改第三页", "乙：好的", "甲：改完发我", "乙：今晚弄"]))
    stitcher.add_page(
        make_page(
            ["甲：先把目录重排", "乙：行", "甲：记得改第三页", "乙：好的", "甲：改完发我", "乙：今晚弄"],
        ),
        direction=-1,
    )
    stitcher.add_page(
        make_page(
            ["甲：记得改第三页", "乙：好的", "甲：改完发我", "乙：今晚弄", "甲：辛苦了", "乙：没事"],
        ),
        direction=1,
    )
    assert texts(stitcher) == [
        "甲：先把目录重排",
        "乙：行",
        "甲：记得改第三页",
        "乙：好的",
        "甲：改完发我",
        "乙：今晚弄",
        "甲：辛苦了",
        "乙：没事",
    ]
    assert not stitcher.breakpoints


# ---------------------------------------------------------------------------
# Repeated short lines
# ---------------------------------------------------------------------------

def test_repeated_short_phrase_is_preserved_not_collapsed():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["好的", "在吗", "好的", "晚安"]))
    stitcher.add_page(make_page(["在吗", "好的", "晚安", "好的"]))
    out = texts(stitcher)
    assert out.count("好的") == 3          # two already there + one truly new
    assert out == ["好的", "在吗", "好的", "晚安", "好的"]


def test_two_consecutive_identical_lines_are_kept():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["在吗", "好的", "好的", "我先忙了"]))
    stitcher.add_page(make_page(["好的", "好的", "我先忙了", "回头聊"]))
    out = texts(stitcher)
    assert out.count("好的") == 2
    assert out == ["在吗", "好的", "好的", "我先忙了", "回头聊"]


def test_repeated_line_is_placed_by_coordinates_not_by_first_text_hit():
    """Doc has "好的" twice; the page shows the *later* copy plus its neighbours.

    Text alone would happily match the earlier copy. The rigid offset (dy) of
    the nearby unique line must pull the match to the later copy.
    """
    stitcher = TranscriptStitcher()
    stitcher.add_page(
        make_page(["好的", "甲：下午三点", "乙：收到", "好的", "甲：不见不散", "乙：好"])
    )
    # Page starts at the second "好的": its y offset differs from the doc copy at
    # index 0 by many line heights, so only the index-3 copy can fit.
    report = stitcher.add_page(make_page(["好的", "甲：不见不散", "乙：好", "乙：我出发了"]))
    assert report.kind == "merged"
    assert report.inserted_after == 1
    assert texts(stitcher).count("好的") == 2
    assert texts(stitcher)[-1] == "乙：我出发了"


def test_wrong_copy_of_repeated_line_is_rejected_by_geometry():
    """Same texts as the doc's first block, but the y spacing is inconsistent.

    A page whose lines cannot be one rigid translation of the document must not
    merge: doing so would silently reorder a conversation.
    """
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["好的", "晚安", "明天见", "早点睡"]))
    # "好的" claims dy = 0 - 44 = -44; "晚安" claims dy = 50 - 66 = -16.
    page = make_page(["好的", "晚安"], y0=0.0)
    page[1].y = 50.0
    report = stitcher.add_page(page)
    assert report.kind == "break"
    assert len(stitcher.breakpoints) == 1


# ---------------------------------------------------------------------------
# OCR noise
# ---------------------------------------------------------------------------

def test_one_mistyped_line_still_aligns_and_is_not_duplicated():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["甲：今天下午三点开会", "乙：你确定吗", "甲：我确定", "乙：好的"]))
    # "我确足" is one wrong character; "你确定吗" on screen above it pins dy.
    report = stitcher.add_page(make_page(["乙：你确定吗", "甲：我确足", "乙：好的", "甲：那我先准备"]))
    assert report.kind == "merged"
    assert report.inserted_middle == 0
    assert texts(stitcher)[-1] == "甲：那我先准备"
    out = texts(stitcher)
    assert out.count("甲：我确定") == 1
    assert "甲：我确足" not in out


def test_higher_confidence_variant_repairs_an_earlier_typo():
    stitcher = TranscriptStitcher()
    # A blurry first frame produced one wrong character at low confidence.
    stitcher.add_page(make_page(["甲：朋天九点出发", "乙：好的"], confidence=0.55))
    # The next frame sees the same line cleanly with higher confidence.
    stitcher.add_page(make_page(["甲：明天九点出发", "乙：好的", "甲：别迟到"], confidence=0.94))
    out = texts(stitcher)
    assert out[0] == "甲：明天九点出发"
    assert "甲：朋天九点出发" not in out
    assert stitcher.lines[0].corrected == 1


def test_two_generic_lines_without_coordinates_cannot_anchor_a_page():
    """No boxes + only two short lines + a strict line threshold => breakpoint."""
    stitcher = TranscriptStitcher(min_overlap_lines=3)
    left = make_page(["好的", "晚安"])
    right = make_page(["晚安", "再见"])
    for line in left + right:
        line.has_geometry = False
        line.y = line.x = 0.0
    stitcher.add_page(left)
    report = stitcher.add_page(right)
    assert report.kind == "break"
    assert len(stitcher.breakpoints) == 1


# ---------------------------------------------------------------------------
# Breakpoints
# ---------------------------------------------------------------------------

def test_no_overlap_marks_breakpoint_and_keeps_content():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["一", "二", "三"]))
    report = stitcher.add_page(make_page(["八", "九", "十"]))
    assert report.kind == "break"
    assert report.breakpoint is True
    assert len(stitcher.breakpoints) == 1
    # Nothing is dropped: the orphan page is kept, with a visible marker.
    assert texts(stitcher) == ["一", "二", "三", "八", "九", "十"]
    text = stitcher.text()
    assert "〔断点 1" in text
    assert "八" in text


def test_upward_breakpoint_lands_above_the_previous_page():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["一", "二", "三"]))
    stitcher.add_page(make_page(["甲", "乙", "丙"]), direction=-1)
    # The upward jump goes above the previous page's top, not to the very end.
    assert texts(stitcher) == ["甲", "乙", "丙", "一", "二", "三"]
    assert len(stitcher.breakpoints) == 1


def test_multiple_breakpoints_are_numbered_in_text():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["一"]))
    stitcher.add_page(make_page(["九"]))
    stitcher.add_page(make_page(["百"]))
    text = stitcher.text()
    assert "〔断点 1" in text
    assert "〔断点 2" in text
    assert stitcher.text(include_breakpoints=False).count("〔") == 0


def test_breakpoint_marker_survives_later_insertions():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["一", "乙：那我们周六早上八点在地铁口见面然后再一起去吃早饭"]))
    stitcher.add_page(make_page(["九", "十"]))          # breakpoint between 二 and 九
    # An upward-ish page that ends on the long line and carries two new lines
    # above the break: they must be inserted before the marker's block.
    stitcher.add_page(
        make_page(["乙：那我们周六早上八点在地铁口见面然后再一起去吃早饭", "三", "四"])
    )
    text = stitcher.text()
    assert "〔断点 1" in text
    assert text.index("四") < text.index("〔断点 1") < text.index("九")


# ---------------------------------------------------------------------------
# Breakpoint repair (scroll back to fill the hole)
#
# These two tests reproduce the "补采之后断点还在、还多了重复行" bug: after a
# jump the lower segment is parked with guessed coordinates, so a page that
# spans the seam cannot align rigidly against *both* segments at once unless the
# stitcher treats the parked segment's geometry as unknown.
# ---------------------------------------------------------------------------

BRIDGE_LINES = [
    "甲：明天下午三点的评审改到四点半",
    "乙：那我四点前到",
    "甲：会议室换到二楼大间",
    "乙：需要带电脑吗",
    "甲：带上投影转接头",
    "乙：我先去打印材料",
    "甲：顺便把上周的纪要带上",
    "乙：纪要存在共享盘里",
    "甲：那你直接打开就行",
    "乙：好的我记住了",
    "甲：还有别的事吗",
    "乙：暂时没有了",
]


def test_scroll_back_fills_the_gap_and_clears_the_breakpoint():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(BRIDGE_LINES[0:5]))
    report = stitcher.add_page(make_page(BRIDGE_LINES[7:12]))
    assert report.kind == "break"
    assert len(stitcher.breakpoints) == 1

    # The user scrolls back until the missing two lines (5, 6) are on screen;
    # the page now holds lines 4..9, i.e. content from both sides of the seam.
    report = stitcher.add_page(make_page(BRIDGE_LINES[4:10]), direction=-1)
    assert report.kind == "merged"
    assert report.inserted_middle == 2
    assert report.resolved_breakpoints == 1
    assert texts(stitcher) == BRIDGE_LINES
    assert stitcher.breakpoints == []
    assert "〔断点" not in stitcher.text()


def test_long_jump_then_rollback_pages_rebuild_without_duplicates():
    """Acceptance scenario: jump 0 -> 13, then roll back 9 / 5 / 9 / 13 / 17 / 22.

    Eight visible rows per page, integer row starts, 5 rows (8..12) lost by the
    jump. Every missing line must come back exactly once and the breakpoint
    opened by the jump must be cleared once a page really bridges the seam.
    """
    truth = build_transcript(30)
    plan = [(0, 0), (13, 1), (9, -1), (5, -1), (9, 1), (13, 1), (17, 1), (22, 1)]
    stitcher = TranscriptStitcher()
    for start, direction in plan:
        stitcher.add_page(make_page(truth[start:start + 8]), direction=direction)
    assert stitcher.text_lines == truth
    assert len(stitcher.lines) == len(truth)
    assert stitcher.breakpoints == []
    assert "〔断点" not in stitcher.text()


def test_bridging_page_does_not_duplicate_the_parked_segment():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(BRIDGE_LINES[0:5]))
    stitcher.add_page(make_page(BRIDGE_LINES[7:12]))
    # Downward re-read that starts on the last line above the seam: the page
    # touches both sides, so the seam is proven and nothing may be duplicated.
    stitcher.add_page(make_page(BRIDGE_LINES[4:11]), direction=1)
    out = texts(stitcher)
    assert out == BRIDGE_LINES
    assert out.count(BRIDGE_LINES[4]) == 1
    assert stitcher.breakpoints == []


def test_a_page_covering_the_seam_without_new_lines_still_clears_the_breakpoint():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(BRIDGE_LINES[0:5]))
    stitcher.add_page(make_page(BRIDGE_LINES[7:12]))
    report = stitcher.add_page(make_page(BRIDGE_LINES[3:9]), direction=-1)
    assert report.kind == "merged"
    assert report.inserted_middle == 2
    assert texts(stitcher) == BRIDGE_LINES
    assert stitcher.breakpoints == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_lines_without_boxes_still_stitch_by_text():
    left = make_page(["甲：周末要不要一起去爬山", "乙：可以啊我正好有空", "甲：那就周六早上八点出发"])
    right = make_page(["乙：可以啊我正好有空", "甲：那就周六早上八点出发", "乙：几点在哪里集合"])
    for line in left + right:
        line.has_geometry = False
        line.y = line.x = 0.0
    stitcher = TranscriptStitcher()
    stitcher.add_page(left)
    report = stitcher.add_page(right)
    assert report.kind == "merged"
    assert texts(stitcher)[-1] == "乙：几点在哪里集合"


def test_single_long_line_can_anchor_when_only_one_line_overlaps():
    long_line = "甲：明天上午十点在公司一楼大厅集合然后一起出发去团建地点"
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["一", long_line, "乙：收到"]))
    # One new line above the long line; only the long line overlaps (dy = 0).
    report = stitcher.add_page(
        make_page(["乙：好的我定闹钟", long_line]), direction=-1
    )
    assert report.kind == "merged"
    assert report.matched_lines == 1
    assert texts(stitcher) == ["一", "乙：好的我定闹钟", long_line, "乙：收到"]


def test_empty_page_is_ignored():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["一", "二"]))
    report = stitcher.add_page([])
    assert report.kind == "empty"
    assert texts(stitcher) == ["一", "二"]


def test_noise_only_line_is_dropped_at_page_build_time():
    assert make_page_line("——") is None
    assert make_page_line("   ") is None
    assert make_page_line("好的") is not None


def test_reset_clears_everything():
    stitcher = TranscriptStitcher()
    stitcher.add_page(make_page(["一", "二"]))
    stitcher.reset()
    assert texts(stitcher) == []
    assert stitcher.stats["pages"] == 0


def test_match_key_is_aggressive_but_display_text_is_not():
    # NFKC folds full-width punctuation to ASCII; whitespace is removed.
    assert match_key(" 你 好 ，， WORLD ！ ") == "你好,world!"
    assert match_key("ＡＢＣ") == "abc"
    pl = make_page_line(" 你 好 ，， ")
    assert pl is not None and pl.text == "你 好 ，，"
    assert pl.norm == "你好,"


def test_similarity_tolerates_small_errors():
    assert line_similarity("今天下午三点开会", "今天下午三点开会议") > 0.85
    assert line_similarity("今天下午三点开会", "明天上午十点出发") < 0.4


# ---------------------------------------------------------------------------
# OCR plumbing
# ---------------------------------------------------------------------------

def test_page_lines_from_ocr_sorts_nothing_and_keeps_boxes():
    result = OCRResult(
        raw_text="甲\n乙",
        normalized_text="甲 乙",
        lines=[
            OCRLine(text="甲：在吗", confidence=0.9, box=[[10, 0], [200, 0], [200, 18], [10, 18]]),
            OCRLine(text="乙：在", confidence=0.8, box=[[10, 22], [200, 22], [200, 40], [10, 40]]),
        ],
        confidence=0.85,
        timestamp=now_ts(),
    )
    page = page_lines_from_ocr(result)
    assert [p.text for p in page] == ["甲：在吗", "乙：在"]
    assert page[0].has_geometry and page[0].y == 0 and page[1].y == 22


def test_page_lines_from_ocr_ignores_empty_and_noise():
    result = OCRResult(
        raw_text="",
        normalized_text="",
        lines=[OCRLine(text="   ", confidence=0.0, box=[]), OCRLine(text="——", confidence=0.5, box=[])],
        timestamp=now_ts(),
    )
    assert page_lines_from_ocr(result) == []


def test_stitch_pages_helper_runs_a_sequence():
    pages = [make_page(["一", "二", "三"]), make_page(["二", "三", "四"])]
    stitcher = stitch_pages(pages)
    assert texts(stitcher) == ["一", "二", "三", "四"]
    assert stitcher.stats["pages"] == 2

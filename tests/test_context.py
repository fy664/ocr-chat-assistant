"""Context manager tests: add, dedup, merge on scroll, limits, clear."""
from __future__ import annotations

from app.context.manager import ContextManager
from app.models.schemas import OCRLine


def test_add_and_get():
    manager = ContextManager(max_messages=20, max_chars=8000)
    assert manager.update_from_text("你好") is True
    assert manager.update_from_text("你好\n在吗") is True
    context = manager.get_context()
    assert [m.content for m in context.messages] == ["你好", "在吗"]


def test_dedup_identical_snapshot():
    manager = ContextManager(max_messages=20, max_chars=8000)
    manager.update_from_text("你好")
    assert manager.update_from_text("你好") is False
    assert manager.size == 1


def test_dedup_consecutive_duplicates_in_snapshot():
    manager = ContextManager(max_messages=20, max_chars=8000)
    manager.update_from_text("你好\n你好")
    assert [m.content for m in manager.get_context().messages] == ["你好"]


def test_suffix_merge_appends_only_new():
    manager = ContextManager(max_messages=20, max_chars=8000)
    manager.update_from_text("A\nB\nC")
    manager.update_from_text("A\nB\nC\nD")
    assert [m.content for m in manager.get_context().messages] == ["A", "B", "C", "D"]


def test_merge_on_scroll_keeps_visible_set():
    """Scrolled window (A,B gone, E appended): visible set stays authoritative."""
    manager = ContextManager(max_messages=20, max_chars=8000)
    manager.update_from_text("A\nB\nC\nD")
    manager.update_from_text("C\nD\nE")
    assert [m.content for m in manager.get_context().messages] == ["C", "D", "E"]


def test_message_limit_keeps_newest():
    manager = ContextManager(max_messages=5, max_chars=8000)
    # one visible snapshot containing 10 messages -> only the newest 5 kept
    manager.update_from_text("\n".join(f"消息{i}" for i in range(10)))
    messages = [m.content for m in manager.get_context().messages]
    assert messages == [f"消息{i}" for i in range(5, 10)]


def test_char_limit_keeps_newest():
    manager = ContextManager(max_messages=20, max_chars=12)
    manager.update_from_text("11111\n22222\n33333")
    messages = [m.content for m in manager.get_context().messages]
    total = sum(len(m) for m in messages)
    assert total <= 12
    assert messages[-1] == "33333"


def test_clear():
    manager = ContextManager(max_messages=20, max_chars=8000)
    manager.update_from_text("你好")
    manager.clear()
    assert manager.size == 0
    assert manager.get_context().messages == []


def test_ocr_jitter_line_merges():
    manager = ContextManager(max_messages=20, max_chars=8000)
    line_a1 = OCRLine(text="A", confidence=0.9, box=[[10, 10], [60, 10], [60, 28], [10, 28]])
    line_b1 = OCRLine(text="你好吗", confidence=0.9, box=[[10, 60], [120, 60], [120, 78], [10, 78]])
    line_a2 = OCRLine(text="A", confidence=0.9, box=[[10, 10], [60, 10], [60, 28], [10, 28]])
    line_b2 = OCRLine(text="你好 吗", confidence=0.9, box=[[10, 60], [120, 60], [120, 78], [10, 78]])
    manager.update_from_ocr([line_a1, line_b1], region_width=400.0)
    # next snapshot: same content with slight OCR noise on the last line
    manager.update_from_ocr([line_a2, line_b2], region_width=400.0)
    contents = [m.content for m in manager.get_context().messages]
    assert len(contents) == 2
    assert contents[0] == "A"
    assert contents[1] in ("你好吗", "你好 吗")


def test_ocr_segmentation_groups_multiline_message():
    manager = ContextManager(max_messages=20, max_chars=8000)
    # two close vertical lines in the same column -> one message
    line1 = OCRLine(text="你周末", confidence=0.9, box=[[10, 10], [80, 10], [80, 28], [10, 28]])
    line2 = OCRLine(text="有空吗", confidence=0.9, box=[[10, 32], [80, 32], [80, 50], [10, 50]])
    manager.update_from_ocr([line1, line2], region_width=400.0)
    assert manager.size == 1
    assert manager.get_context().messages[0].content == "你周末 有空吗"


def test_speaker_heuristic():
    from app.context.builder import segment_messages
    from app.utils.time import now_ts

    other = OCRLine(text="对方消息", confidence=0.9, box=[[10, 10], [120, 10], [120, 28], [10, 28]])
    self_msg = OCRLine(text="我的消息", confidence=0.9, box=[[280, 40], [390, 40], [390, 58], [280, 58]])
    middle = OCRLine(text="中间消息", confidence=0.9, box=[[170, 70], [230, 70], [230, 88], [170, 88]])
    messages = segment_messages([other, self_msg, middle], region_width=400.0, timestamp=now_ts())
    by_content = {m.content: m for m in messages}
    assert by_content["对方消息"].speaker == "对方"
    assert by_content["我的消息"].speaker == "我"
    assert by_content["中间消息"].speaker is None

    # heuristic can be disabled
    messages = segment_messages([other], region_width=400.0, timestamp=now_ts(), speaker_heuristic=False)
    assert messages[0].speaker is None

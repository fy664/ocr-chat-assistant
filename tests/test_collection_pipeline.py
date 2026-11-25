"""Controller-level tests for continuous scrolling collection.

A fake capture session feeds pre-built OCR texts to the real controller, so the
test covers the wiring (queue, direction, stitcher, drain, media policy)
without any screen capture or PaddleOCR.
"""
from __future__ import annotations

import threading

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from app.analysis.decoder import DecoderController
from app.models.schemas import ScreenRegion
from tests.helpers import StubOCREngine, make_frame, wait_until

REGION = ScreenRegion(x=100, y=100, width=400, height=300)

# Three screens of one conversation with two lines of overlap each.
PAGE_TEXTS = [
    "甲：明天几点开会\n乙：九点半\n甲：会议室在二楼",
    "乙：九点半\n甲：会议室在二楼\n乙：知道了",
    "甲：会议室在二楼\n乙：知道了\n甲：别迟到",
]

EXPECTED = [
    "甲：明天几点开会",
    "乙：九点半",
    "甲：会议室在二楼",
    "乙：知道了",
    "甲：别迟到",
]


class FakeSession(QObject):
    frame_ready = Signal(object, int)
    paused = Signal(str)
    resumed = Signal()
    state_changed = Signal(str)
    error = Signal(str)
    status_changed = Signal(dict)

    def __init__(self, region):
        super().__init__()
        self.region = region
        self.started = False
        self.stopped = False
        self.closed = False
        self.final = None

    def start(self):
        self.started = True
        self.state_changed.emit("采集中")

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    def capture_now(self):
        return self.final


def build(make_settings, session_holder):
    settings = make_settings(
        scroll_capture_interval_ms=700,
        scroll_max_queue=6,
        scroll_match_threshold=0.70,
        scroll_min_overlap_lines=2,
        vision_enabled=True,
    )
    engine = StubOCREngine(texts=list(PAGE_TEXTS))

    def session_factory(region):
        session = FakeSession(region)
        session_holder.append(session)
        return session

    controller = DecoderController(
        settings,
        mock_llm=True,
        ocr_engine_factory=lambda: engine,
        session_factory=session_factory,
    )
    return controller, engine


def test_collection_pipeline_rebuilds_one_transcript(qapp, make_settings):
    holder: list[FakeSession] = []
    controller, engine = build(make_settings, holder)
    states: list[str] = []
    hints: list[str] = []
    controller.state_changed.connect(states.append)
    controller.collection_hint.connect(hints.append)

    assert controller.start_collection(REGION) is True
    session = holder[0]
    assert session.started
    assert controller.busy is True
    assert states[-1] == "采集中"

    for index in range(len(PAGE_TEXTS)):
        session.frame_ready.emit(make_frame(), 1)
    assert wait_until(qapp, lambda: engine.calls == len(PAGE_TEXTS), timeout_ms=8000)

    completed: list[dict] = []
    controller.collection_completed.connect(completed.append)
    session.final = make_frame()
    controller.stop_collection()
    assert wait_until(qapp, lambda: completed, timeout_ms=8000)

    payload = completed[0]
    lines = payload["text"].splitlines()
    assert lines == EXPECTED
    assert payload["pages"] == len(PAGE_TEXTS) + 1     # + the final frame
    assert payload["breakpoints"] == []
    assert payload["dropped"] == 0
    assert payload["lines"] == len(EXPECTED)
    assert controller.busy is False
    assert controller.collecting is False
    assert session.closed
    controller.shutdown()


def test_up_scroll_direction_is_forwarded_to_the_stitcher(qapp, make_settings):
    """The first frame is the newest screen; scrolling up prepends history."""
    holder: list[FakeSession] = []
    settings = make_settings(scroll_match_threshold=0.70, scroll_min_overlap_lines=2)
    engine = StubOCREngine(texts=[PAGE_TEXTS[2], PAGE_TEXTS[0]])
    controller = DecoderController(
        settings,
        mock_llm=True,
        ocr_engine_factory=lambda: engine,
        session_factory=lambda region: holder.append(FakeSession(region)) or holder[-1],
    )
    assert controller.start_collection(REGION) is True
    session = holder[0]

    session.frame_ready.emit(make_frame(), 1)    # newest screen on the doc
    session.frame_ready.emit(make_frame(), -1)   # user scrolls up: older history
    assert wait_until(qapp, lambda: engine.calls == 2, timeout_ms=8000)

    stitcher = controller.stitcher
    assert stitcher is not None
    assert stitcher.text_lines[:2] == ["甲：明天几点开会", "乙：九点半"]
    assert stitcher.text_lines[-2:] == ["乙：知道了", "甲：别迟到"]
    assert len(stitcher.lines) == 5
    controller.stop_collection()
    assert wait_until(qapp, lambda: not controller.busy, timeout_ms=8000)
    controller.shutdown()


def test_pause_and_resume_are_reported_to_the_ui(qapp, make_settings):
    holder: list[FakeSession] = []
    controller, _engine = build(make_settings, holder)
    hints: list[str] = []
    controller.collection_hint.connect(hints.append)
    assert controller.start_collection(REGION) is True
    session = holder[0]

    session.paused.emit("前台窗口没有覆盖选区（可能切换了聊天窗口）")
    assert any("暂停" in h for h in hints)
    session.resumed.emit()
    assert any("恢复" in h for h in hints)
    controller.stop_collection()
    controller.shutdown()


def test_single_shot_path_still_works(qapp, make_settings):
    """Collecting must not break the existing one-screenshot entry point."""
    settings = make_settings(vision_enabled=False)
    controller = DecoderController(
        settings,
        mock_llm=True,
        ocr_engine_factory=lambda: StubOCREngine(texts=["甲：在吗\n乙：在"]),
    )
    done: list[str] = []
    controller.capture_completed.connect(done.append)
    controller.set_region(REGION)
    controller.capture(REGION)
    assert wait_until(qapp, lambda: done, timeout_ms=8000)
    assert done[0] == "甲：在吗\n乙：在"
    assert controller.busy is False
    controller.shutdown()


def test_capture_is_refused_while_collecting(qapp, make_settings):
    holder: list[FakeSession] = []
    controller, _engine = build(make_settings, holder)
    messages: list[str] = []
    controller.status_message.connect(messages.append)
    assert controller.start_collection(REGION) is True
    controller.capture(REGION)
    assert any("连续采集" in m for m in messages)
    controller.stop_collection()
    controller.shutdown()


class GatedEngine:
    """Stub engine whose first call blocks, so "stop" can land mid-recognition."""

    def __init__(self, texts):
        self.inner = StubOCREngine(texts=texts)
        self.gate = threading.Event()
        self.blocked = threading.Event()

    def recognize(self, image):
        if self.inner.calls == 0:
            self.blocked.set()
            self.gate.wait(10)
        return self.inner.recognize(image)


def test_finish_waits_for_a_result_that_is_still_on_its_way(qapp, make_settings):
    """``worker.is_idle`` is not enough: results hop threads before being merged.

    Regression for "3 frames already recognised, clicked stop, only 3 lines
    came out": the drain loop saw an idle worker while one result was still
    queued in the main thread, finished early, detached the stitcher, and the
    arriving result was dropped.
    """
    holder: list[FakeSession] = []
    controller, _engine = build(make_settings, holder)
    completed: list[dict] = []
    controller.collection_completed.connect(completed.append)
    assert controller.start_collection(REGION) is True
    session = holder[0]

    controller.stop_collection()  # starts the 150 ms drain timer
    controller._inflight.add(999)  # stands in for a result still in transit
    wait_until(qapp, lambda: False, timeout_ms=400)  # a few drain ticks, none may finish
    assert completed == []

    controller._inflight.discard(999)
    assert wait_until(qapp, lambda: completed, timeout_ms=3000)
    controller.shutdown()


def test_three_recognised_frames_then_immediate_stop_still_yields_five_lines(qapp, make_settings):
    """The reported sequence: 3 frames recognised, click stop at once, 5 expected."""
    holder: list[FakeSession] = []
    controller, engine = build(make_settings, holder)
    completed: list[dict] = []
    controller.collection_completed.connect(completed.append)
    assert controller.start_collection(REGION) is True
    session = holder[0]

    for _ in range(len(PAGE_TEXTS)):
        session.frame_ready.emit(make_frame(), 1)
    assert wait_until(qapp, lambda: engine.calls == len(PAGE_TEXTS), timeout_ms=8000)
    # No final frame in this round: exactly the 3 recognised pages.
    controller.stop_collection()

    assert wait_until(qapp, lambda: completed, timeout_ms=8000)
    payload = completed[0]
    assert payload["text"].splitlines() == EXPECTED
    assert payload["pages"] == len(PAGE_TEXTS)
    controller.shutdown()


def test_late_result_from_a_previous_round_is_dropped(qapp, make_settings):
    """An OCR result arriving after 清除/重开 belongs to the old transcript."""
    holder: list[FakeSession] = []
    controller, engine = build(make_settings, holder)
    assert controller.start_collection(REGION) is True
    holder[0].frame_ready.emit(make_frame(), 1)
    assert wait_until(qapp, lambda: engine.calls == 1, timeout_ms=8000)

    controller.clear()                       # user wipes the session
    assert wait_until(qapp, lambda: not controller.collecting)

    assert controller.start_collection(REGION) is True   # fresh round, no frames yet
    stale = StubOCREngine(texts=["甲：上一轮的残留\n乙：不该出现"]).recognize(None)
    controller._on_ocr_sequenced(1, stale)   # delivered late, seq 1 is not registered

    stitcher = controller.stitcher
    assert stitcher is not None and stitcher.lines == []
    controller.stop_collection()
    controller.shutdown()


def test_stop_while_the_last_frame_is_being_recognised_keeps_it(qapp, make_settings):
    """End-to-end version of the same bug: the final frame must survive."""
    holder: list[FakeSession] = []
    settings = make_settings(
        scroll_capture_interval_ms=700,
        scroll_max_queue=6,
        scroll_match_threshold=0.70,
        scroll_min_overlap_lines=2,
        vision_enabled=True,
    )
    engine = GatedEngine(texts=[PAGE_TEXTS[0], PAGE_TEXTS[1]])
    controller = DecoderController(
        settings,
        mock_llm=True,
        ocr_engine_factory=lambda: engine,
        session_factory=lambda region: holder.append(FakeSession(region)) or holder[-1],
    )
    completed: list[dict] = []
    controller.collection_completed.connect(completed.append)
    assert controller.start_collection(REGION) is True
    session = holder[0]

    session.frame_ready.emit(make_frame(), 1)
    assert engine.blocked.wait(5)  # frame 1 is inside recognize() right now

    session.final = make_frame()
    controller.stop_collection()  # user clicks 结束采集 mid-recognition
    engine.gate.set()

    assert wait_until(qapp, lambda: completed, timeout_ms=8000)
    payload = completed[0]
    assert payload["text"].splitlines() == EXPECTED[:4]
    assert payload["pages"] == 2
    assert controller.busy is False
    controller.shutdown()


@pytest.mark.parametrize(
    ("first_text", "final_pixel", "expected_calls"),
    [(PAGE_TEXTS[0], 20, 1), (PAGE_TEXTS[0], 30, 2), ("", 20, 2)],
)
def test_final_frame_reuses_only_identical_successful_ocr(
    qapp, make_settings, first_text, final_pixel, expected_calls,
):
    sessions = []

    def session_factory(region):
        session = FakeSession(region)
        sessions.append(session)
        return session

    def frame_with_pixel(pixel):
        return make_frame().model_copy(update={"image": np.full((8, 8, 3), pixel, dtype=np.uint8)})

    engine = StubOCREngine(texts=[first_text, PAGE_TEXTS[1]])
    controller = DecoderController(
        make_settings(vision_enabled=False),
        mock_llm=True,
        ocr_engine_factory=lambda: engine,
        session_factory=session_factory,
    )
    completed = []
    controller.collection_completed.connect(completed.append)
    try:
        assert controller.start_collection(REGION)
        session = sessions[0]
        session.frame_ready.emit(frame_with_pixel(20), 1)
        assert wait_until(qapp, lambda: controller.stitcher.page_count == 1)
        session.final = frame_with_pixel(final_pixel)
        controller.stop_collection()
        assert wait_until(qapp, lambda: completed)
        assert engine.calls == expected_calls
        if expected_calls == 1:
            assert completed[0]["text"] == PAGE_TEXTS[0]
        else:
            assert completed[0]["text"].endswith(PAGE_TEXTS[1].splitlines()[-1])
    finally:
        controller.shutdown()

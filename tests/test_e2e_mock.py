"""End-to-end mock test (spec section 74):

    Fake screenshot -> Mock OCR -> text changed -> Context -> Mock LLM
    -> AnalysisResult -> UI update

The whole pipeline runs without a real API key and without a real screen:
frames are pushed directly into the scheduler, OCR runs on the real OCR
worker thread against the stub engine, the LLM runs on the real LLM worker
thread against MockLLMClient, and a real MainWindow verifies the UI update.
"""
from __future__ import annotations

import pytest

from app.analysis.scheduler import AppState, PipelineScheduler
from app.llm.client import MockLLMClient
from app.models.schemas import ScreenRegion
from app.ui.main_window import MainWindow
from tests.helpers import StubOCREngine, make_frame, wait_until

REGION = ScreenRegion(x=0, y=0, width=400, height=300)


@pytest.fixture()
def e2e(qapp, make_settings):
    settings = make_settings(debounce_ms=300, capture_interval_ms=500)
    scheduler = PipelineScheduler(
        settings,
        llm_factory=lambda: MockLLMClient(marker="e2e"),
        ocr_engine_factory=lambda: StubOCREngine(texts=[]),
    )
    window = MainWindow(scheduler, settings)
    window.show()
    qapp.processEvents()
    yield scheduler, window
    window.close()
    qapp.processEvents()
    scheduler.shutdown()


def test_full_pipeline_updates_ui(qapp, e2e):
    scheduler, window = e2e

    # program the worker's stub engine with the "visible chat" snapshots
    assert wait_until(qapp, lambda: scheduler._ocr_worker.engine is not None, timeout_ms=3000)
    stub: StubOCREngine = scheduler._ocr_worker.engine
    stub.texts = [
        "对方：你周末有空吗",                 # baseline
        "对方：你周末有空吗\n我：应该有吧",    # change 1
        "对方：你周末有空吗\n我：应该有吧\n对方：怎么不回我",  # change 2 (during debounce)
    ]

    # simulate user selecting a region and starting monitoring
    scheduler.set_region_and_restart(REGION, resume_after=False)
    scheduler._start(take_baseline=True)
    scheduler._monitor.stop()  # frames are pushed manually below

    # Frame 1: baseline (no analysis)
    scheduler._on_frame(make_frame())
    assert wait_until(qapp, lambda: "你周末有空吗" in scheduler._latest_ocr_text, timeout_ms=3000)
    assert scheduler.state == AppState.MONITORING

    # Frame 2+3: rapid changes -> debounce -> ONE analysis with full context
    completed = []
    scheduler.analysis_completed.connect(completed.append)

    scheduler._on_frame(make_frame())
    assert wait_until(qapp, lambda: "应该有吧" in scheduler._latest_ocr_text, timeout_ms=3000)
    scheduler._on_frame(make_frame())
    assert wait_until(qapp, lambda: "怎么不回我" in scheduler._latest_ocr_text, timeout_ms=3000)

    ok = wait_until(qapp, lambda: len(completed) >= 1, timeout_ms=6000)
    assert ok, "analysis did not complete"

    # UI was updated with the structured result
    assert window._cards.current_result is not None
    assert "[e2e]" in window._cards.current_result.surface_meaning
    assert window._replies._layout.count() == 3  # 3 suggested replies with copy buttons

    # context contains all three messages (spec 96.E: A B C, not only C)
    context = scheduler._context.get_context()
    contents = [m.content for m in context.messages]
    assert any("你周末有空吗" in c for c in contents)
    assert any("应该有吧" in c for c in contents)
    assert any("怎么不回我" in c for c in contents)

    # state machine finished at SHOWING_RESULT
    assert scheduler.state == AppState.SHOWING_RESULT


def test_pause_blocks_pipeline(qapp, e2e):
    scheduler, window = e2e
    assert wait_until(qapp, lambda: scheduler._ocr_worker.engine is not None, timeout_ms=3000)
    stub: StubOCREngine = scheduler._ocr_worker.engine
    stub.texts = ["你好"]

    scheduler.set_region_and_restart(REGION, resume_after=False)
    scheduler._start(take_baseline=True)
    scheduler._monitor.stop()

    scheduler._on_frame(make_frame())
    assert wait_until(qapp, lambda: scheduler._latest_ocr_text == "你好", timeout_ms=3000)

    scheduler.pause()
    assert scheduler.state == AppState.PAUSED
    assert not scheduler._monitor.is_running

    scheduler._on_frame(make_frame())  # ignored while paused
    qapp.processEvents()
    assert scheduler.state == AppState.PAUSED

    scheduler.resume()
    assert scheduler.state == AppState.MONITORING
    scheduler._monitor.stop()  # keep the test deterministic

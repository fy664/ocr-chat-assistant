"""Scheduler (realtime pipeline) unit tests: state machine, debounce,
generation/stale handling, pause/resume, clear, min-chars, scroll.

These drive the scheduler's GUI-thread handlers directly; the full
worker-thread path is covered by test_e2e_mock.py.
"""
from __future__ import annotations

import time

from app.analysis.scheduler import AppState, PipelineScheduler
from app.llm.client import MockLLMClient
from app.models.schemas import OCRLine, OCRResult, ScreenRegion
from app.ocr.normalize import normalize_text
from app.utils.time import now_ts
from tests.helpers import wait_until

REGION = ScreenRegion(x=0, y=0, width=400, height=300)


def make_result(text: str) -> OCRResult:
    lines = []
    y = 10.0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(OCRLine(text=line, confidence=0.9,
                             box=[[10.0, y], [200.0, y], [200.0, y + 18.0], [10.0, y + 18.0]]))
        y += 22.0
    return OCRResult(raw_text=text, normalized_text=normalize_text(text),
                     lines=lines, confidence=0.9, timestamp=now_ts())


def _drive_ocr(scheduler: PipelineScheduler, text: str) -> None:
    scheduler._on_ocr_completed(make_result(text))


def test_no_api_key_analysis_fails_gracefully(qapp, scheduler_factory):
    scheduler = scheduler_factory()  # no llm_clients -> unconfigured
    failures = []
    scheduler.analysis_failed.connect(failures.append)
    scheduler._region = REGION
    _drive_ocr(scheduler, "你好")
    scheduler._debounce.stop()  # drive debounce directly (deterministic)
    scheduler._on_debounce_fired()
    assert failures and "API Key" in failures[0]
    assert scheduler.state == AppState.MONITORING  # keeps watching


def test_normal_analysis_flow(qapp, scheduler_factory):
    client = MockLLMClient(marker="ok")
    scheduler = scheduler_factory(llm_clients=[client])
    completed = []
    contexts = []
    scheduler.analysis_completed.connect(completed.append)
    scheduler.context_changed.connect(contexts.append)
    scheduler._region = REGION
    _drive_ocr(scheduler, "你周末有空吗")
    ok = wait_until(qapp, lambda: len(completed) >= 1, timeout_ms=4000)
    assert ok, "analysis did not complete in time"
    assert "[ok]" in completed[0].surface_meaning
    assert len(client.calls) == 1
    assert scheduler.state == AppState.SHOWING_RESULT
    assert contexts, "context should have been updated before analysis"
    assert "你周末有空吗" in [m.content for m in contexts[-1].messages]


def test_debounce_merges_rapid_changes(qapp, scheduler_factory):
    client = MockLLMClient()
    scheduler = scheduler_factory(llm_clients=[client])  # debounce 300ms
    completed = []
    scheduler.analysis_completed.connect(completed.append)
    scheduler._region = REGION

    t0 = time.monotonic()
    _drive_ocr(scheduler, "你周末有空吗")
    _drive_ocr(scheduler, "你周末有空吗\n怎么不回我")
    _drive_ocr(scheduler, "你周末有空吗\n怎么不回我\n是不是不想出来")

    ok = wait_until(qapp, lambda: len(completed) >= 1, timeout_ms=5000)
    elapsed = time.monotonic() - t0
    assert ok, "analysis did not complete in time"
    # rapid changes must NOT fire three requests
    assert len(client.calls) == 1
    # debounce waited for text stability
    assert elapsed >= 0.25


def test_stale_generation_never_overrides_new_result(qapp, scheduler_factory):
    slow_a = MockLLMClient(delay=0.45, marker="A")
    fast_b = MockLLMClient(delay=0.05, marker="B")
    scheduler = scheduler_factory(llm_clients=[slow_a, fast_b])
    completed = []
    scheduler.analysis_completed.connect(completed.append)
    scheduler._region = REGION

    _drive_ocr(scheduler, "第一版文本")
    scheduler._debounce.stop()               # deterministic: no real timer race
    scheduler._on_debounce_fired()           # gen 1 -> slow A
    _drive_ocr(scheduler, "第一版文本\n第二版文本")
    scheduler._debounce.stop()
    scheduler._on_debounce_fired()           # gen 2 -> fast B (queued behind A)

    ok = wait_until(qapp, lambda: len(completed) >= 1, timeout_ms=5000)
    assert ok
    # only the newest generation's result is accepted
    assert len(completed) == 1
    assert "[B]" in completed[0].surface_meaning
    # A's result arrived later but was dropped as stale
    time.sleep(0.6)
    qapp.processEvents()
    assert len(completed) == 1


def test_llm_error_keeps_monitoring(qapp, scheduler_factory):
    client = MockLLMClient(fail=True)
    scheduler = scheduler_factory(llm_clients=[client])
    failures = []
    scheduler.analysis_failed.connect(failures.append)
    scheduler._region = REGION

    _drive_ocr(scheduler, "你好")
    ok = wait_until(qapp, lambda: len(failures) >= 1, timeout_ms=4000)
    assert ok
    assert "Mock LLM 故障" in failures[0]
    assert scheduler.state == AppState.MONITORING  # continues watching for next change


def test_ocr_error_does_not_crash(qapp, scheduler_factory):
    scheduler = scheduler_factory()
    scheduler._region = REGION
    scheduler._set_state(AppState.MONITORING)
    scheduler._on_ocr_failed("boom", 0.0)
    assert scheduler.state == AppState.MONITORING
    # next frame still processed
    _drive_ocr(scheduler, "你好")


def test_pause_resume_with_baseline(qapp, scheduler_factory):
    client = MockLLMClient()
    scheduler = scheduler_factory(llm_clients=[client])
    scheduler._region = REGION

    # wait for the (stub) engine to become ready so resume() works
    assert wait_until(qapp, lambda: scheduler._engine_ready, timeout_ms=3000)

    scheduler._start(take_baseline=True)
    scheduler._monitor.stop()  # tests drive frames manually
    scheduler._on_ocr_completed(make_result("旧消息"))
    assert scheduler.state == AppState.MONITORING
    assert client.calls == []  # baseline never analyzed

    scheduler.pause()
    assert scheduler.state == AppState.PAUSED
    assert not scheduler._monitor.is_running
    _drive_ocr(scheduler, "暂停期间的新消息")  # ignored while paused
    qapp.processEvents()
    assert client.calls == []

    scheduler.resume()
    assert scheduler.state == AppState.MONITORING
    # resume baseline: no analysis, old text not resubmitted
    _drive_ocr(scheduler, "暂停期间的新消息")
    assert client.calls == []

    # a genuinely new change triggers analysis
    _drive_ocr(scheduler, "暂停期间的新消息\n恢复后的新消息")
    assert wait_until(qapp, lambda: len(client.calls) >= 1, timeout_ms=4000)


def test_clear_context_resets_baseline(qapp, scheduler_factory):
    client = MockLLMClient()
    scheduler = scheduler_factory(llm_clients=[client])
    cleared = []
    scheduler.cleared.connect(lambda: cleared.append(True))
    scheduler._region = REGION

    _drive_ocr(scheduler, "你好")
    assert wait_until(qapp, lambda: len(client.calls) >= 1, timeout_ms=4000)

    scheduler.clear_context()
    assert cleared
    assert scheduler._context.size == 0
    # after clear, the same text is the baseline -> no re-analysis
    _drive_ocr(scheduler, "你好")
    qapp.processEvents()
    assert len(client.calls) == 1


def test_short_text_does_not_trigger_llm(qapp, scheduler_factory, make_settings):
    settings = make_settings(debounce_ms=300, min_ocr_chars=5)
    client = MockLLMClient()
    scheduler = scheduler_factory(settings=settings, llm_clients=[client])
    scheduler._region = REGION

    _drive_ocr(scheduler, "你好")  # 2 effective chars < 5
    time.sleep(0.5)
    qapp.processEvents()
    assert client.calls == []
    assert scheduler.state == AppState.MONITORING


def test_pure_scroll_does_not_trigger_llm(qapp, scheduler_factory):
    client = MockLLMClient()
    scheduler = scheduler_factory(llm_clients=[client])
    scheduler._region = REGION

    _drive_ocr(scheduler, "A\nB\nC")
    assert wait_until(qapp, lambda: len(client.calls) >= 1, timeout_ms=4000)

    # scrolled up: subset of seen lines, nothing new
    _drive_ocr(scheduler, "A\nB")
    time.sleep(0.5)
    qapp.processEvents()
    assert len(client.calls) == 1

    # scrolled back down: still only seen lines
    _drive_ocr(scheduler, "A\nB\nC")
    time.sleep(0.5)
    qapp.processEvents()
    assert len(client.calls) == 1


def test_apply_settings_updates_timers(qapp, scheduler_factory, make_settings):
    scheduler = scheduler_factory()
    new_settings = make_settings(capture_interval_ms=2000, debounce_ms=1200,
                                 max_context_messages=30, max_context_chars=5000)
    scheduler.apply_settings(new_settings)
    assert scheduler._monitor._timer.interval() == 2000
    assert scheduler._debounce.interval() == 1200
    assert scheduler._context.max_messages == 30
    assert scheduler._context.max_chars == 5000


def test_state_texts_cover_all_states(qapp, scheduler_factory):
    from app.analysis.scheduler import STATE_TEXT

    scheduler = scheduler_factory()
    for state in AppState:
        scheduler._set_state(state)
        assert STATE_TEXT[state]

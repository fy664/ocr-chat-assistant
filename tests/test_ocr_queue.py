"""Tests for the sequenced OCR queue (continuous capture mode)."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from app.analysis.workers import OCRWorkerThread
from app.models.schemas import OCRResult
from tests.helpers import wait_until


class RecordingEngine:
    """Returns the frame payload as text so ordering is observable."""

    def __init__(self):
        self.calls: list[str] = []

    def recognize(self, image) -> OCRResult:
        self.calls.append(image)
        return OCRResult(raw_text=str(image), normalized_text=str(image), timestamp=0.0)


class BlockingEngine:
    """Blocks the worker so a backlog can be built deterministically."""

    def __init__(self):
        self.gate = threading.Event()
        self.started = threading.Event()

    def recognize(self, image) -> OCRResult:
        self.started.set()
        self.gate.wait(10)
        return OCRResult(raw_text=str(image), normalized_text=str(image))


def item(tag: int):
    return SimpleNamespace(timestamp=float(tag), image=f"frame-{tag}")


def _started(qapp, worker, engine, timeout_ms=5000):
    return wait_until(qapp, lambda: worker.engine is not None, timeout_ms=timeout_ms)


def test_sequenced_frames_are_processed_in_submission_order(qapp):
    engine = RecordingEngine()
    worker = OCRWorkerThread(lambda: engine)
    results: list[tuple[int, str]] = []
    worker.ocr_sequenced.connect(lambda seq, res: results.append((seq, res.raw_text)))
    worker.start()
    assert _started(qapp, worker, engine)
    worker.set_max_queue(8)

    seqs = [worker.submit_sequenced(item(i)) for i in range(1, 6)]
    assert seqs == [1, 2, 3, 4, 5]
    assert wait_until(qapp, lambda: len(results) == 5, timeout_ms=6000)
    assert results == [(i, f"frame-{i}") for i in range(1, 6)]
    assert worker.pending_count == 0
    assert worker.is_idle

    worker.stop()
    assert worker.wait(3000)


def test_full_queue_rejects_the_newest_frame_and_reports_it(qapp):
    engine = BlockingEngine()
    worker = OCRWorkerThread(lambda: engine)
    worker.set_max_queue(2)
    dropped: list[int] = []
    worker.queue_full.connect(lambda n: dropped.append(n))
    worker.start()
    assert _started(qapp, worker, engine)

    assert worker.submit_sequenced(item(1)) == 1
    assert wait_until(qapp, lambda: engine.started.is_set())
    # Two slots behind the frame being processed, then the queue is full.
    assert worker.submit_sequenced(item(2)) is not None
    assert worker.submit_sequenced(item(3)) is not None
    assert worker.submit_sequenced(item(4)) is None
    assert worker.submit_sequenced(item(5)) is None
    assert wait_until(qapp, lambda: len(dropped) == 2)
    assert dropped == [1, 2]
    assert worker.dropped_count == 2

    engine.gate.set()
    assert wait_until(qapp, lambda: worker.is_idle, timeout_ms=6000)
    worker.stop()
    assert worker.wait(3000)


def test_clear_queue_drops_waiting_frames_only(qapp):
    engine = BlockingEngine()
    worker = OCRWorkerThread(lambda: engine)
    worker.set_max_queue(4)
    worker.start()
    assert _started(qapp, worker, engine)

    worker.submit_sequenced(item(1))
    assert wait_until(qapp, lambda: engine.started.is_set())
    worker.submit_sequenced(item(2))
    worker.submit_sequenced(item(3))
    assert worker.pending_count == 3  # one processing + two waiting
    assert worker.clear_queue() == 2
    assert worker.pending_count == 1

    engine.gate.set()
    assert wait_until(qapp, lambda: worker.is_idle, timeout_ms=6000)
    worker.stop()
    assert worker.wait(3000)


def test_taken_frame_still_counts_as_pending(qapp):
    """A frame handed to the worker is not "idle" until it is recognised.

    The queue pop and the ``processing`` flag used to be two separate steps
    (pop inside the lock, flag set afterwards in ``run``). In that gap
    ``pending_count`` dropped to zero and ``is_idle`` claimed the worker had
    nothing left - which is exactly the moment "stop collecting" used to
    finish and drop the last frame.
    """
    engine = BlockingEngine()
    worker = OCRWorkerThread(lambda: engine)  # never started: no thread involved
    assert worker.submit_sequenced(item(1)) == 1

    frame, seq = worker._take_pending()
    assert seq == 1
    assert frame.image == "frame-1"
    assert worker.processing is True
    assert worker.pending_count == 1
    assert not worker.is_idle

    worker._processing = False  # simulate the worker finishing the frame


def test_dropped_queue_still_reports_idle_once_drained(qapp):
    """After a drain the worker must look idle again, not stuck in processing."""
    engine = BlockingEngine()
    worker = OCRWorkerThread(lambda: engine)
    worker.start()
    assert _started(qapp, worker, engine)
    worker.set_max_queue(2)
    worker.submit_sequenced(item(1))
    assert wait_until(qapp, lambda: engine.started.is_set())

    engine.gate.set()
    assert wait_until(qapp, lambda: worker.is_idle, timeout_ms=6000)
    assert worker.pending_count == 0
    worker.stop()
    assert worker.wait(3000)


def test_latest_only_submit_still_overwrites(qapp):
    """The single-shot path (one screenshot) must keep its old semantics."""
    engine = BlockingEngine()
    worker = OCRWorkerThread(lambda: engine)
    done: list[str] = []
    worker.ocr_completed.connect(lambda res: done.append(res.raw_text))
    worker.start()
    assert _started(qapp, worker, engine)

    worker.submit(item(1))
    assert wait_until(qapp, lambda: engine.started.is_set())
    worker.submit(item(2))
    worker.submit(item(3))  # overwrites item(2) before it is ever picked up
    engine.gate.set()
    # First frame runs, then the pending slot hands over the *newest* frame;
    # the overwritten one is never recognised at all.
    assert wait_until(qapp, lambda: len(done) == 2, timeout_ms=6000)
    assert done == ["frame-1", "frame-3"]
    worker.stop()
    assert worker.wait(3000)

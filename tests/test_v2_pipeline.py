"""v2 pipeline tests: streaming reasoning, multimodal images, prompt schema."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app.analysis.scheduler import AppState
from app.context.models import ContextMessage, ConversationContext
from app.llm.client import MOCK_RESULT
from app.llm.prompt import build_system_prompt, build_user_prompt
from app.llm.provider import analyze_with_client
from app.models.schemas import OCRLine, OCRResult, ScreenRegion
from app.ocr.normalize import normalize_text
from app.utils.time import now_ts
from tests.helpers import wait_until

REGION = ScreenRegion(x=0, y=0, width=400, height=300)


class StreamingClient:
    """Minimal client exposing a reasoning stream and capturing images."""

    def __init__(self) -> None:
        self.images = None
        self.calls = 0
        self.system_prompt = ""
        self.user_prompt = ""

    def analyze(self, system_prompt: str, context: str, images=None):
        self.calls += 1
        self.system_prompt = system_prompt
        self.user_prompt = context
        self.images = images
        return MOCK_RESULT.model_copy(deep=True)

    def analyze_stream(
        self,
        system_prompt: str,
        context: str,
        images=None,
        *,
        on_reasoning=None,
        on_status=None,
    ):
        self.calls += 1
        self.system_prompt = system_prompt
        self.user_prompt = context
        self.images = images
        if on_status:
            on_status("requesting")
        if on_reasoning:
            on_reasoning("先看证据：这是一条测试消息。\n")
            on_reasoning("再判断意图与情绪，保持保守。\n")
        return MOCK_RESULT.model_copy(deep=True)


class MinimalClient:
    """Legacy client: no images, no streaming callback support."""

    def analyze(self, system_prompt: str, context: str):
        return MOCK_RESULT.model_copy(deep=True)


def _context(text: str) -> ConversationContext:
    return ConversationContext(
        messages=[ContextMessage(content=text, speaker=None, timestamp=0.0)]
    )


def _ocr_result(text: str) -> OCRResult:
    lines = [
        OCRLine(
            text=line,
            confidence=0.9,
            box=[[10.0, 10.0], [300.0, 10.0], [300.0, 28.0], [10.0, 28.0]],
        )
        for line in text.splitlines()
        if line.strip()
    ]
    return OCRResult(
        raw_text=text,
        normalized_text=normalize_text(text),
        lines=lines,
        confidence=0.9,
        timestamp=now_ts(),
    )


def test_system_prompt_requests_thinking_and_vision_quality():
    prompt = build_system_prompt(thinking_enabled=True, vision=True)
    assert "thinking" in prompt
    assert "多模态" in prompt
    assert "evidence" in prompt
    assert "alternatives" in prompt

    no_think = build_system_prompt(thinking_enabled=False, vision=False)
    assert "不要展开长篇隐藏推理" in no_think
    assert "thinking 字段仍要保留" in no_think
    assert "多模态" not in no_think


def test_user_prompt_marks_vision_when_image_attached():
    context = _context("你周末有空吗")
    without = build_user_prompt(context)
    with_vision = build_user_prompt(context, vision=True)
    assert "【画面】" not in without
    assert "【画面】" in with_vision
    assert "附带了当前聊天区域的截图" in with_vision


def test_analyzer_uses_stream_and_marks_vision():
    from app.analysis.analyzer import Analyzer

    client = StreamingClient()
    seen: list[str] = []
    analyzer = Analyzer(client)
    result = analyzer.analyze_context(
        _context("你周末有空吗"),
        images=["data:image/jpeg;base64,AAAA"],
        on_reasoning=seen.append,
    )
    assert client.images == ["data:image/jpeg;base64,AAAA"]
    assert result.vision_used is True
    assert "多模态" in client.system_prompt
    assert seen


def test_analyze_with_client_falls_back_to_legacy_signature():
    client = MinimalClient()
    result = analyze_with_client(client, "system", "context", images=["data:image/jpeg;base64,AAAA"])
    assert result == MOCK_RESULT


def test_scheduler_sends_multimodal_frame(qapp, scheduler_factory, make_settings):
    settings = make_settings(
        debounce_ms=300,
        capture_interval_ms=500,
        vision_enabled=True,
        thinking_enabled=True,
    )
    client = StreamingClient()
    scheduler = scheduler_factory(settings=settings, llm_clients=[client])
    completed = []
    scheduler.analysis_completed.connect(completed.append)
    scheduler._region = REGION
    scheduler._latest_frame = SimpleNamespace(
        image=np.full((48, 64, 3), 96, dtype=np.uint8)
    )

    scheduler._on_ocr_completed(_ocr_result("你周末有空吗"))
    assert wait_until(qapp, lambda: len(completed) >= 1, timeout_ms=5000)
    assert client.images is not None and len(client.images) == 1
    assert client.images[0].startswith("data:image/jpeg;base64,")
    assert "【画面】" in client.user_prompt
    assert completed[0].vision_used is True
    assert scheduler.state == AppState.SHOWING_RESULT


def test_scheduler_skips_vision_when_disabled(qapp, scheduler_factory, make_settings):
    settings = make_settings(
        debounce_ms=300,
        capture_interval_ms=500,
        vision_enabled=False,
        thinking_enabled=True,
    )
    client = StreamingClient()
    scheduler = scheduler_factory(settings=settings, llm_clients=[client])
    completed = []
    scheduler.analysis_completed.connect(completed.append)
    scheduler._region = REGION
    scheduler._latest_frame = SimpleNamespace(
        image=np.full((48, 64, 3), 96, dtype=np.uint8)
    )

    scheduler._on_ocr_completed(_ocr_result("你周末有空吗"))
    assert wait_until(qapp, lambda: len(completed) >= 1, timeout_ms=5000)
    assert client.images is None
    assert "【画面】" not in client.user_prompt

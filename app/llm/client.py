"""Mock LLM client for tests and demo mode (no real API key needed)."""
from __future__ import annotations

import logging
import time

from app.llm.provider import ConnectionTestResult, LLMClient, LLMError
from app.models.schemas import (
    AnalysisResult,
    EmotionResult,
    SuggestedReply,
)

logger = logging.getLogger("ocr_chat.llm.mock")

MOCK_RESULT = AnalysisResult(
    surface_meaning="测试消息",
    possible_intent=["测试意图"],
    emotion=EmotionResult(label="中性", confidence=1.0, evidence="测试"),
    potential_needs=["测试需求"],
    reply_strategy="测试策略",
    suggested_replies=[
        SuggestedReply(style="自然", text="测试回复"),
        SuggestedReply(style="温和", text="测试回复"),
        SuggestedReply(style="简短", text="好的"),
    ],
    uncertainty="这是测试数据",
)


class MockLLMClient:
    """Fixed valid result; optional delay / failure / call recording for tests."""

    def __init__(
        self,
        delay: float = 0.0,
        fail: bool = False,
        marker: str | None = None,
    ) -> None:
        self.delay = delay
        self.fail = fail
        self.marker = marker
        self.calls: list[str] = []

    def analyze(self, system_prompt: str, context: str) -> AnalysisResult:
        self.calls.append(context)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise LLMError("Mock LLM 故障（测试用）")
        result = MOCK_RESULT.model_copy(deep=True)
        if self.marker:
            result.surface_meaning = f"[{self.marker}] {result.surface_meaning}"
        return result

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, message="连接成功\nModel: mock\nLatency: 0 ms", latency_ms=0.0, model="mock")

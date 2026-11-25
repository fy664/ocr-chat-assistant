"""Mock LLM client for tests and demo mode (no real API key needed)."""
from __future__ import annotations

import logging
import time

from app.llm.provider import ConnectionTestResult, LLMError
from app.models.schemas import (
    AnalysisResult,
    ConversationSummary,
    RecentChatEvent,
    EmotionResult,
    SuggestedReply,
)

logger = logging.getLogger("ocr_chat.llm.mock")

MOCK_THINKING = [
    "先看可见证据：这是一条测试消息，没有额外的上下文。",
    "情绪与意图都应保守判断，避免把测试数据当成真实对话。",
    "回复方向：自然承接，不制造不存在的信息。",
]

MOCK_RESULT = AnalysisResult(
    surface_meaning="测试消息",
    possible_intent=["测试意图"],
    emotion=EmotionResult(label="中性", confidence=1.0, evidence="测试"),
    potential_needs=["测试需求"],
    reply_strategy="测试策略",
    suggested_replies=[
        SuggestedReply(style="自然", text="测试回复", why="日常延续话题"),
        SuggestedReply(style="温和", text="测试回复", why="对方需要被认真回应"),
        SuggestedReply(style="简短", text="好的", why="快速确认"),
    ],
    uncertainty="这是测试数据",
    conversation_summary=ConversationSummary(
        overview="这是一份演示总结。对话中的发言者讨论了一个待确认的安排。",
        timeline=["提出安排", "等待确认"], open_questions=["确认下一步安排"],
    ),
    recent_event=RecentChatEvent(topic="确认安排", description="最近一条消息在推进一项安排。",
                                evidence_ids=["M0001"], needs_reply=True),
    thinking=MOCK_THINKING,
    evidence=["测试消息"],
    alternatives=["这条消息也可能只是示例，不包含真实意图"],
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

    def analyze(self, system_prompt: str, context: str, images=None) -> AnalysisResult:
        self.calls.append(context)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise LLMError("Mock LLM 故障（测试用）")
        result = MOCK_RESULT.model_copy(deep=True)
        if self.marker:
            result.surface_meaning = f"[{self.marker}] {result.surface_meaning}"
        if images:
            result.vision_used = True
        return result

    def analyze_stream(
        self,
        system_prompt: str,
        context: str,
        images=None,
        *,
        on_reasoning=None,
        on_status=None,
    ) -> AnalysisResult:
        """Demo-friendly reasoning stream; records exactly one call."""
        if on_status:
            on_status("requesting")
        for index, step in enumerate(MOCK_THINKING):
            if on_reasoning:
                on_reasoning(step + "\n")
            if index == 0 and on_status:
                on_status("first_token")
            time.sleep(0.08)
        return self.analyze(system_prompt, context, images=images)

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, message="连接成功\nModel: mock\nLatency: 0 ms", latency_ms=0.0, model="mock")

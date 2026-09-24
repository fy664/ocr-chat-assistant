"""Analyzer tests: mock LLM success, LLM error propagation, prompt format."""
from __future__ import annotations

import pytest

from app.analysis.analyzer import Analyzer
from app.context.models import ContextMessage, ConversationContext
from app.llm.client import MOCK_RESULT, MockLLMClient
from app.llm.provider import LLMError


def _context(*contents: str) -> ConversationContext:
    messages = []
    t = 0.0
    for content in contents:
        messages.append(ContextMessage(content=content, speaker=None, timestamp=t))
        t += 1.0
    return ConversationContext(messages=messages)


def test_analyzer_with_mock_llm():
    client = MockLLMClient()
    analyzer = Analyzer(client)
    result = analyzer.analyze_context(_context("你周末有空吗"))
    assert result == MOCK_RESULT
    assert len(client.calls) == 1


def test_analyzer_prompt_contains_context():
    client = MockLLMClient()
    analyzer = Analyzer(client)
    analyzer.analyze_context(_context("你周末有空吗", "应该有吧"))
    user_prompt = client.calls[0]
    assert "【聊天上下文】" in user_prompt
    assert "未知：你周末有空吗" in user_prompt
    assert "未知：应该有吧" in user_prompt
    assert "【当前状态】" in user_prompt


def test_analyzer_prompt_empty_context():
    client = MockLLMClient()
    analyzer = Analyzer(client)
    analyzer.analyze_context(_context())
    user_prompt = client.calls[0]
    assert "无可用历史上下文。" in user_prompt


def test_analyzer_prompt_override_appended():
    client = MockLLMClient()
    analyzer = Analyzer(client)
    analyzer.analyze_context(_context("你好"), override_text="用户修正后的文本")
    user_prompt = client.calls[0]
    assert "未知（用户修正后文本）：用户修正后的文本" in user_prompt


def test_analyzer_propagates_llm_error():
    client = MockLLMClient(fail=True)
    analyzer = Analyzer(client)
    with pytest.raises(LLMError):
        analyzer.analyze_context(_context("你好"))

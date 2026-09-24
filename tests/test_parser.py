"""LLM parser tests: valid JSON, Markdown fence, prose, invalid, missing fields."""
from __future__ import annotations

import json

import pytest

from app.llm.parser import LLMParseError, extract_json, parse_analysis
from app.models.schemas import AnalysisResult

VALID = {
    "surface_meaning": "对方在询问周末安排",
    "possible_intent": ["确认时间", "发起邀约"],
    "emotion": {"label": "平静", "confidence": 0.8, "evidence": "用词中性"},
    "potential_needs": ["得到明确答复"],
    "reply_strategy": "直接给出明确时间",
    "suggested_replies": [
        {"style": "自然", "text": "周六下午有空"},
        {"style": "温和", "text": "我周六下午可以哦"},
        {"style": "简短", "text": "可以"},
    ],
    "uncertainty": "仅凭文本无法判断真实情绪",
}


def test_valid_json():
    result = parse_analysis(json.dumps(VALID, ensure_ascii=False))
    assert isinstance(result, AnalysisResult)
    assert result.surface_meaning == "对方在询问周末安排"
    assert result.emotion.confidence == 0.8


def test_markdown_fence_json():
    content = "```json\n" + json.dumps(VALID, ensure_ascii=False) + "\n```"
    result = parse_analysis(content)
    assert isinstance(result, AnalysisResult)


def test_json_wrapped_in_prose():
    content = "好的，分析结果如下：\n" + json.dumps(VALID, ensure_ascii=False) + "\n希望有帮助。"
    result = parse_analysis(content)
    assert isinstance(result, AnalysisResult)


def test_invalid_json_raises():
    with pytest.raises(LLMParseError):
        parse_analysis("这不是 JSON，只是一段话。")


def test_empty_response_raises():
    with pytest.raises(LLMParseError):
        parse_analysis("")


def test_missing_fields_raise():
    data = dict(VALID)
    del data["reply_strategy"]
    with pytest.raises(LLMParseError):
        parse_analysis(json.dumps(data, ensure_ascii=False))


def test_wrong_field_type_raises():
    data = dict(VALID)
    data["suggested_replies"] = "不是列表"
    with pytest.raises(LLMParseError):
        parse_analysis(json.dumps(data, ensure_ascii=False))


def test_extract_json_fence():
    text = "```json\n{\"a\": 1}\n```"
    assert extract_json(text) == '{"a": 1}'


def test_extract_json_no_fence():
    assert extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_raises_without_object():
    with pytest.raises(LLMParseError):
        extract_json("hello world")

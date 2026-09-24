"""Pydantic schema tests: valid data, missing fields, wrong types, invalid confidence."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.schemas import AnalysisResult, EmotionResult, ScreenRegion, SuggestedReply


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


def test_valid_data():
    result = AnalysisResult.model_validate(VALID)
    assert result.emotion.label == "平静"
    assert len(result.suggested_replies) == 3


def test_missing_field():
    data = dict(VALID)
    del data["surface_meaning"]
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(data)


def test_missing_emotion_label_raises():
    # confidence/evidence are optional per spec, but label is required
    data = dict(VALID)
    data["emotion"] = {"confidence": 0.8}
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(data)


def test_emotion_optional_fields_default():
    data = dict(VALID)
    data["emotion"] = {"label": "平静"}
    result = AnalysisResult.model_validate(data)
    assert result.emotion.confidence is None
    assert result.emotion.evidence is None


def test_wrong_type():
    data = dict(VALID)
    data["possible_intent"] = 123  # a non-str, non-list type still fails
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(data)


def test_list_field_accepts_single_string():
    """Real models sometimes return a bare string for a list field."""
    data = dict(VALID)
    data["possible_intent"] = "确认时间"
    data["potential_needs"] = "得到明确答复"
    result = AnalysisResult.model_validate(data)
    assert result.possible_intent == ["确认时间"]
    assert result.potential_needs == ["得到明确答复"]


def test_invalid_confidence():
    with pytest.raises(ValidationError):
        EmotionResult(label="平静", confidence=1.5)
    with pytest.raises(ValidationError):
        EmotionResult(label="平静", confidence=-0.1)


def test_confidence_none_allowed():
    emotion = EmotionResult(label="平静", confidence=None)
    assert emotion.confidence is None


def test_mock_llm_payload_valid():
    """The spec's fixed Mock payload must validate (spec section 69)."""
    mock_payload = {
        "surface_meaning": "测试消息",
        "possible_intent": ["测试意图"],
        "emotion": {"label": "中性", "confidence": 1.0, "evidence": "测试"},
        "potential_needs": ["测试需求"],
        "reply_strategy": "测试策略",
        "suggested_replies": [
            {"style": "自然", "text": "测试回复"},
            {"style": "温和", "text": "测试回复"},
            {"style": "简短", "text": "好的"},
        ],
        "uncertainty": "这是测试数据",
    }
    result = AnalysisResult.model_validate(mock_payload)
    assert result.suggested_replies[2].text == "好的"


def test_screen_region():
    region = ScreenRegion(x=-100, y=0, width=400, height=300)  # negative origin monitor
    assert region.mss_box == {"left": -100, "top": 0, "width": 400, "height": 300}
    with pytest.raises(ValidationError):
        ScreenRegion(x=0, y=0, width=0, height=300)


def test_suggested_reply():
    reply = SuggestedReply(style="自然", text="好的")
    assert reply.style == "自然"

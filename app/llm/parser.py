"""LLM response parsing: extract JSON -> parse -> Pydantic validation."""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.models.schemas import AnalysisResult

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class LLMParseError(RuntimeError):
    pass


def extract_json(content: str) -> str:
    """Pull the JSON object out of model output (handles Markdown fences
    and surrounding prose)."""
    if not content or not content.strip():
        raise LLMParseError("AI 返回内容为空")
    text = content.strip()
    match = _FENCE_RE.search(text)
    if match:
        text = match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise LLMParseError("未找到 JSON 对象")
    return text[start : end + 1]


def parse_analysis(content: str) -> AnalysisResult:
    """Parse + validate one LLM response into AnalysisResult."""
    json_text = extract_json(content)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise LLMParseError(f"JSON 解析失败: {exc}") from exc
    try:
        return AnalysisResult.model_validate(data)
    except ValidationError as exc:
        raise LLMParseError(f"Schema 校验失败（{exc.error_count()} 个字段错误）") from exc

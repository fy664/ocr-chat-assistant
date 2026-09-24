"""LLM provider abstraction.

Business code only knows `LLMClient` - never a vendor-specific class.
Switching providers is a config change (api_key/base_url/model), not a
code change.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

from app.llm.parser import LLMParseError, parse_analysis
from app.llm.prompt import REPAIR_SYSTEM_PROMPT, build_repair_user_prompt
from app.models.schemas import AnalysisResult

logger = logging.getLogger("ocr_chat.llm")


class LLMError(RuntimeError):
    """Friendly, user-readable LLM failure. Never contains the API key."""


class LLMNotConfiguredError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


@dataclass
class LLMConfig:
    provider_name: str
    api_key: str
    base_url: str
    model: str
    temperature: float = 0.3
    timeout: float = 30.0


@dataclass
class ConnectionTestResult:
    ok: bool
    message: str
    latency_ms: float | None = None
    model: str | None = None


class LLMClient(Protocol):
    def analyze(self, system_prompt: str, context: str) -> AnalysisResult: ...

    def test_connection(self) -> ConnectionTestResult: ...


def _friendly_error(exc: Exception) -> str:
    """Map SDK/HTTP exceptions to short user-readable messages."""
    try:
        import openai

        if isinstance(exc, openai.AuthenticationError):
            return "API Key 无效（HTTP 401）"
        if isinstance(exc, openai.PermissionDeniedError):
            return "API Key 无权限（HTTP 403）"
        if isinstance(exc, openai.NotFoundError):
            return "模型不存在或 Base URL 错误（HTTP 404）"
        if isinstance(exc, openai.RateLimitError):
            return "请求频率过高（HTTP 429）"
        if isinstance(exc, openai.InternalServerError):
            return "服务暂时不可用（HTTP 5xx）"
        if isinstance(exc, openai.APITimeoutError):
            return "网络请求超时"
        if isinstance(exc, openai.APIConnectionError):
            return "网络连接失败"
    except Exception:
        pass
    if isinstance(exc, LLMResponseError):
        return "AI 返回格式异常，请重新分析。"
    if isinstance(exc, LLMParseError):
        return "AI 返回格式异常，请重新分析。"
    return f"LLM 请求失败（{type(exc).__name__}）"


class OpenAICompatibleClient:
    """Unified OpenAI-compatible client (works with any compliant provider)."""

    def __init__(self, config: LLMConfig, max_retries: int = 1):
        self._config = config
        self._max_retries = max_retries

    # ---- LLMClient interface ----------------------------------------------

    def analyze(self, system_prompt: str, context: str) -> AnalysisResult:
        raw = self._chat(system_prompt, context)
        try:
            return parse_analysis(raw)
        except LLMParseError as exc:
            logger.warning("first JSON parse failed, attempting one repair retry: %s", exc)
            raw2 = self._chat(REPAIR_SYSTEM_PROMPT, build_repair_user_prompt(raw, str(exc)))
            try:
                return parse_analysis(raw2)
            except LLMParseError as exc2:
                raise LLMResponseError("AI 返回格式异常，请重新分析。") from exc2

    def test_connection(self) -> ConnectionTestResult:
        start = time.monotonic()
        try:
            client = self._make_client()
            response = client.chat.completions.create(
                model=self._config.model,
                messages=[{"role": "user", "content": "请只回复：OK"}],
                max_tokens=8,
                temperature=0.0,
            )
            content = (response.choices[0].message.content or "").strip()
            latency_ms = (time.monotonic() - start) * 1000
            if not content:
                return ConnectionTestResult(ok=False, message="连接失败\n原因：invalid response")
            return ConnectionTestResult(
                ok=True,
                message=f"连接成功\nModel: {self._config.model}\nLatency: {latency_ms:.0f} ms",
                latency_ms=latency_ms,
                model=self._config.model,
            )
        except Exception as exc:
            return ConnectionTestResult(ok=False, message=f"连接失败\n原因：{_friendly_error(exc)}")

    # ---- internals ----------------------------------------------------------

    def _make_client(self):
        import openai

        return openai.OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=self._config.timeout,
            max_retries=self._max_retries,
        )

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        try:
            client = self._make_client()
            response = client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._config.temperature,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(_friendly_error(exc)) from exc
        try:
            content = response.choices[0].message.content or ""
        except (IndexError, AttributeError):
            content = ""
        if not content.strip():
            raise LLMResponseError("AI 返回内容为空")
        return content


def create_llm_client(settings) -> LLMClient:
    """Build the configured client. Raises LLMNotConfiguredError without a key."""
    if not settings.is_llm_configured:
        raise LLMNotConfiguredError("请先配置 LLM API Key。")
    config = LLMConfig(
        provider_name=settings.llm_provider or "custom",
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
    )
    return OpenAICompatibleClient(config, max_retries=1)

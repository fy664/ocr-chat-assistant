"""LLM provider abstraction.

Business code only knows a tiny duck-typed client: ``analyze`` (and optionally
``analyze_stream`` for providers that expose a native reasoning channel).
Switching providers is a config change (api_key/base_url/model), not a code
change.
"""
from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from app.llm.parser import LLMParseError, parse_analysis
from app.llm.prompt import REPAIR_SYSTEM_PROMPT, build_repair_user_prompt
from app.models.schemas import AnalysisResult
from app.utils.logger import register_secret

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
    max_tokens: int | None = None


@dataclass
class ConnectionTestResult:
    ok: bool
    message: str
    latency_ms: float | None = None
    model: str | None = None


class LLMClient(Protocol):
    def analyze(self, system_prompt: str, context: str, images=None) -> AnalysisResult: ...

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
        if isinstance(exc, openai.BadRequestError):
            return "模型不接受请求参数（HTTP 400，可能不支持该图片或字段）"
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


def _reasoning_delta(delta) -> str:
    """Best-effort extraction of provider-specific reasoning deltas."""
    for attribute in ("reasoning_content", "reasoning"):
        value = getattr(delta, attribute, None)
        if isinstance(value, str) and value:
            return value
    extra = getattr(delta, "model_extra", None)
    if isinstance(extra, dict):
        for key in ("reasoning_content", "reasoning"):
            value = extra.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _reasoning_steps(text: str, limit: int = 12) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in text.replace("\r", "\n").split("\n") if part.strip()]
    if len(parts) == 1:
        # Fall back to sentence-ish chunks for providers that stream one long line.
        parts = [chunk.strip() for chunk in text.replace("。", "。\n").split("\n") if chunk.strip()]
    return [part[:240] for part in parts[:limit]]


def analyze_with_client(
    client,
    system_prompt: str,
    user_prompt: str,
    *,
    images: list[str] | None = None,
    on_reasoning=None,
    on_status=None,
) -> AnalysisResult:
    """Call the richest supported client API without breaking older mocks.

    A client may implement only ``analyze(system, user)``. Signature inspection
    keeps that path working while letting our clients receive images/callbacks.
    """
    stream = getattr(client, "analyze_stream", None)
    if on_reasoning is not None and callable(stream):
        kwargs = {}
        params = inspect.signature(stream).parameters
        if "images" in params:
            kwargs["images"] = images
        if "on_reasoning" in params:
            kwargs["on_reasoning"] = on_reasoning
        if "on_status" in params:
            kwargs["on_status"] = on_status
        return stream(system_prompt, user_prompt, **kwargs)

    analyze = client.analyze
    params = inspect.signature(analyze).parameters
    kwargs = {}
    if "images" in params and images:
        kwargs["images"] = images
    return analyze(system_prompt, user_prompt, **kwargs)


class OpenAICompatibleClient:
    """Unified OpenAI-compatible client (works with any compliant provider)."""

    def __init__(self, config: LLMConfig, max_retries: int = 1):
        self._config = config
        register_secret(config.api_key)
        self._max_retries = max_retries
        self._sdk_client = None

    # ---- LLMClient interface ----------------------------------------------

    def summarize_history(self, system_prompt: str, context: str) -> str:
        return self._chat(system_prompt, context, max_tokens=1100)

    def analyze(self, system_prompt: str, context: str, images=None) -> AnalysisResult:
        raw = self._chat(system_prompt, context, images=images)
        try:
            return parse_analysis(raw)
        except LLMParseError as exc:
            logger.warning("first JSON parse failed, attempting one repair retry: %s", exc)
            raw2 = self._chat(
                REPAIR_SYSTEM_PROMPT,
                build_repair_user_prompt(raw, str(exc)),
                images=None,
            )
            try:
                return parse_analysis(raw2)
            except LLMParseError as exc2:
                raise LLMResponseError("AI 返回格式异常，请重新分析。") from exc2

    def analyze_stream(
        self,
        system_prompt: str,
        context: str,
        images=None,
        *,
        on_reasoning=None,
        on_status=None,
    ) -> AnalysisResult:
        """Stream the response, forwarding native reasoning content.

        The final JSON is collected and parsed exactly like ``analyze``. If the
        provider does not expose reasoning, callbacks simply never fire.
        """
        if on_status:
            on_status("requesting")
        reasoning_parts: list[str] = []
        content_parts: list[str] = []
        first_token = False

        try:
            client = self._make_client()
            request = {
                "model": self._config.model,
                "messages": self._build_messages(system_prompt, context, images),
                "temperature": self._config.temperature,
                "stream": True,
            }
            if self._config.max_tokens:
                request["max_tokens"] = int(self._config.max_tokens)
            stream = client.chat.completions.create(**request)
            for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                reasoning = _reasoning_delta(delta)
                if reasoning:
                    reasoning_parts.append(reasoning)
                    if not first_token:
                        first_token = True
                        if on_status:
                            on_status("first_token")
                    if on_reasoning:
                        on_reasoning(reasoning)
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    if not first_token:
                        first_token = True
                        if on_status:
                            on_status("first_token")
                    content_parts.append(content)
        except LLMError:
            raise
        except Exception as exc:
            # Some OpenAI-compatible gateways do not implement streaming or
            # image content. If nothing was emitted yet, retry non-streaming
            # once so a text-only analysis still succeeds.
            if not first_token and not content_parts and not reasoning_parts:
                if on_status:
                    on_status("fallback")
                logger.warning("streaming unavailable, falling back to non-stream (%s)", type(exc).__name__)
                return self.analyze(system_prompt, context, images=images)
            raise LLMError(_friendly_error(exc)) from exc

        raw = "".join(content_parts)
        try:
            if not raw.strip():
                raise LLMResponseError("AI 返回内容为空")
            result = parse_analysis(raw)
        except LLMParseError as exc:
            logger.warning("streamed JSON parse failed, attempting one repair retry: %s", exc)
            try:
                raw2 = self._chat(
                    REPAIR_SYSTEM_PROMPT,
                    build_repair_user_prompt(raw, str(exc)),
                    images=None,
                )
                result = parse_analysis(raw2)
            except LLMParseError as exc2:
                raise LLMResponseError("AI 返回格式异常，请重新分析。") from exc2
        except LLMResponseError:
            raise

        if reasoning_parts and not result.thinking:
            result.thinking = _reasoning_steps("".join(reasoning_parts))
        if images:
            result.vision_used = True
        if on_status:
            on_status("parsing")
        return result

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

        if self._sdk_client is None:
            self._sdk_client = openai.OpenAI(
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                timeout=self._config.timeout,
                max_retries=self._max_retries,
            )
        return self._sdk_client

    def close(self) -> None:
        client, self._sdk_client = self._sdk_client, None
        if client is not None:
            client.close()

    def _build_messages(self, system_prompt: str, user_prompt: str, images=None):
        if not images:
            user_content = user_prompt
        else:
            user_content = [{"type": "text", "text": user_prompt}]
            for data_url in images:
                if not data_url:
                    continue
                user_content.append(
                    {"type": "image_url", "image_url": {"url": data_url}}
                )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _chat(self, system_prompt: str, user_prompt: str, images=None, *, max_tokens=None) -> str:
        try:
            client = self._make_client()
            request = {
                "model": self._config.model,
                "messages": self._build_messages(system_prompt, user_prompt, images),
                "temperature": self._config.temperature,
            }
            token_limit = max_tokens if max_tokens is not None else self._config.max_tokens
            if token_limit:
                request["max_tokens"] = int(token_limit)
            response = client.chat.completions.create(**request)
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


def create_llm_client(settings, max_tokens: int | None = None) -> LLMClient:
    """Build the configured client. Raises LLMNotConfiguredError without a key."""
    if not settings.is_llm_configured:
        raise LLMNotConfiguredError("请先配置 LLM API Key。")
    token_limit = max_tokens
    if token_limit is None:
        token_limit = getattr(settings, "llm_max_tokens", None)
    config = LLMConfig(
        provider_name=settings.llm_provider or "custom",
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
        max_tokens=token_limit,
    )
    return OpenAICompatibleClient(config, max_retries=1)

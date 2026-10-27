"""Analyzer: Context -> Prompt -> LLM -> validated AnalysisResult."""
from __future__ import annotations

import logging

from app.context.models import ConversationContext
from app.llm.prompt import build_system_prompt, build_user_prompt
from app.llm.provider import analyze_with_client
from app.models.schemas import AnalysisResult

logger = logging.getLogger("ocr_chat.analyzer")


class Analyzer:
    def __init__(self, client) -> None:
        self._client = client

    def analyze_context(
        self,
        context: ConversationContext,
        override_text: str | None = None,
        *,
        images: list[str] | None = None,
        thinking_enabled: bool = True,
        on_reasoning=None,
        on_status=None,
    ) -> AnalysisResult:
        """Analyze a context. ``images`` are encoded data URLs, not raw frames."""
        vision = bool(images)
        system_prompt = build_system_prompt(
            thinking_enabled=thinking_enabled,
            vision=vision,
        )
        user_prompt = build_user_prompt(
            context,
            override_text=override_text,
            vision=vision,
            thinking_enabled=thinking_enabled,
        )
        result = analyze_with_client(
            self._client,
            system_prompt,
            user_prompt,
            images=images,
            on_reasoning=on_reasoning,
            on_status=on_status,
        )
        if vision:
            result.vision_used = True
        logger.info(
            "analysis completed: %d context messages, %d replies, thinking=%d",
            len(context.messages),
            len(result.suggested_replies),
            len(result.thinking),
        )
        return result


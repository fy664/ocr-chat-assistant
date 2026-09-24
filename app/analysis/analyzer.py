"""Analyzer: Context -> Prompt -> LLM -> validated AnalysisResult."""
from __future__ import annotations

import logging

from app.context.models import ConversationContext
from app.llm.prompt import SYSTEM_PROMPT, build_user_prompt
from app.models.schemas import AnalysisResult

logger = logging.getLogger("ocr_chat.analyzer")


class Analyzer:
    def __init__(self, client) -> None:
        self._client = client

    def analyze_context(
        self,
        context: ConversationContext,
        override_text: str | None = None,
    ) -> AnalysisResult:
        user_prompt = build_user_prompt(context, override_text=override_text)
        result = self._client.analyze(SYSTEM_PROMPT, user_prompt)
        logger.info("analysis completed: %d context messages, %d replies",
                    len(context.messages), len(result.suggested_replies))
        return result

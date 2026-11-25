"""Qt adapter for the conversation agent."""
from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from app.agent.conversation import AgentCancelled, ConversationAgent, ConversationRequest
from app.llm.provider import LLMError

logger = logging.getLogger("ocr_chat.agent")


class ConversationWorker(QThread):
    reasoning = Signal(int, str)
    status = Signal(int, str)
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, token: int, client, request: ConversationRequest, parent=None):
        super().__init__(parent)
        self._token = token
        self._client = client
        self._request = request

    def run(self) -> None:
        try:
            result = ConversationAgent(self._client).run(
                self._request,
                on_reasoning=lambda text: self.reasoning.emit(self._token, text),
                on_status=lambda phase: self.status.emit(self._token, phase),
                cancelled=self.isInterruptionRequested,
            )
        except AgentCancelled:
            return
        except Exception as exc:
            if not self.isInterruptionRequested():
                logger.warning("conversation analysis failed (%s)", type(exc).__name__)
                message = str(exc) if isinstance(exc, LLMError) else "解读失败，请重试。"
                self.failed.emit(self._token, message)
        else:
            if not self.isInterruptionRequested():
                self.completed.emit(self._token, result)
        finally:
            close = getattr(self._client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    logger.warning("client cleanup failed (%s)", type(exc).__name__)

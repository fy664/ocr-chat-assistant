"""Rolling conversation context.

Snapshots are merged incrementally instead of blindly appended:
  - consecutive duplicate lines inside one snapshot are collapsed;
  - incoming lines are diffed against the existing tail with
    difflib.SequenceMatcher (autojunk off), so:
      * appends           -> only the new lines are added
      * OCR jitter lines  -> the corrected line replaces the old one
      * scrolls           -> scrolled-away lines drop, visible set is kept
  - hard limits (message count / char count) always keep the newest content.
"""
from __future__ import annotations

import logging
from difflib import SequenceMatcher

from app.context.builder import segment_messages, split_text_messages
from app.context.models import ContextMessage, ConversationContext
from app.models.schemas import OCRLine
from app.utils.time import now_ts

logger = logging.getLogger("ocr_chat.context")


class ContextManager:
    def __init__(self, max_messages: int = 20, max_chars: int = 8000):
        self.max_messages = max_messages
        self.max_chars = max_chars
        self._messages: list[ContextMessage] = []

    # ---- public API -------------------------------------------------------

    def update_from_ocr(
        self,
        lines: list[OCRLine],
        region_width: float,
        timestamp: float | None = None,
        speaker_heuristic: bool = True,
    ) -> bool:
        timestamp = timestamp or now_ts()
        incoming = segment_messages(lines, region_width, timestamp, speaker_heuristic)
        return self.merge(incoming)

    def update_from_text(
        self,
        text: str,
        timestamp: float | None = None,
    ) -> bool:
        timestamp = timestamp or now_ts()
        incoming = split_text_messages(text, timestamp)
        return self.merge(incoming)

    def merge(self, incoming: list[ContextMessage]) -> bool:
        incoming = self._collapse_consecutive_duplicates(incoming)
        if not incoming:
            return False

        old_contents = [m.content for m in self._messages]
        new_contents = [m.content for m in incoming]

        matcher = SequenceMatcher(None, old_contents, new_contents, autojunk=False)
        merged: list[ContextMessage] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                merged.extend(self._messages[i1:i2])
            elif tag == "delete":
                continue  # scrolled-away / superseded content
            else:  # insert / replace
                merged.extend(incoming[j1:j2])

        if [m.content for m in merged] == old_contents and len(merged) == len(self._messages):
            return False

        self._messages = merged
        self._trim()
        return True

    def get_context(self) -> ConversationContext:
        return ConversationContext(messages=[m.model_copy(deep=True) for m in self._messages])

    @property
    def size(self) -> int:
        return len(self._messages)

    def clear(self) -> None:
        self._messages = []

    def set_limits(self, max_messages: int, max_chars: int) -> None:
        self.max_messages = max_messages
        self.max_chars = max_chars
        self._trim()

    # ---- internals --------------------------------------------------------

    @staticmethod
    def _collapse_consecutive_duplicates(messages: list[ContextMessage]) -> list[ContextMessage]:
        out: list[ContextMessage] = []
        for message in messages:
            if out and out[-1].content == message.content:
                continue
            out.append(message)
        return out

    def _trim(self) -> None:
        while len(self._messages) > self.max_messages:
            self._messages.pop(0)
        while (
            len(self._messages) > 1
            and sum(len(m.content) for m in self._messages) > self.max_chars
        ):
            self._messages.pop(0)

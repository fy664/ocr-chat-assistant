"""Context data structures.

Speaker assignment is a *heuristic* only: OCR cannot reliably know who
said what. `speaker` is "对方"/"我" when the left/right position heuristic
is confident enough, otherwise None ("未知"). The heuristic is never
presented as fact.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

SPEAKER_OTHER = "对方"
SPEAKER_SELF = "我"
SPEAKER_UNKNOWN = "未知"


class ContextMessage(BaseModel):
    content: str
    speaker: str | None = None
    timestamp: float
    speaker_source: str = "unknown"  # "heuristic" | "unknown"

    @property
    def speaker_label(self) -> str:
        return self.speaker or SPEAKER_UNKNOWN


class ConversationContext(BaseModel):
    messages: list[ContextMessage] = Field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return sum(len(m.content) for m in self.messages)

    def to_prompt_lines(self) -> list[str]:
        return [f"{m.speaker_label}：{m.content}" for m in self.messages]

    def to_display_lines(self) -> list[str]:
        out: list[str] = []
        for m in self.messages:
            if m.speaker and m.speaker_source == "heuristic":
                out.append(f"{m.speaker}：{m.content}")
            else:
                out.append(f"{m.content}")
        return out

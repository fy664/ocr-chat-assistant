"""Shared data schemas.

Every AI output MUST pass Pydantic validation before it reaches the UI.
Screenshots are memory-only: frames hold a numpy array reference and are
released as soon as OCR finishes.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScreenRegion(BaseModel):
    """Selected screen area in *physical* pixels (mss coordinate space)."""

    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @property
    def mss_box(self) -> dict[str, int]:
        return {"left": self.x, "top": self.y, "width": self.width, "height": self.height}

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2


class ScreenshotFrame(BaseModel):
    """One captured frame. `image` is an in-memory RGB uint8 ndarray."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    x: int
    y: int
    width: int
    height: int
    timestamp: float
    image: Any


class OCRLine(BaseModel):
    text: str
    confidence: float = 0.0
    box: list[list[float]] = Field(default_factory=list)

    @property
    def x_center(self) -> float:
        if not self.box:
            return 0.0
        xs = [p[0] for p in self.box if p]
        return sum(xs) / len(xs) if xs else 0.0

    @property
    def top(self) -> float:
        ys = [p[1] for p in self.box if p]
        return min(ys) if ys else 0.0

    @property
    def bottom(self) -> float:
        ys = [p[1] for p in self.box if p]
        return max(ys) if ys else 0.0

    @property
    def left(self) -> float:
        xs = [p[0] for p in self.box if p]
        return min(xs) if xs else 0.0

    @property
    def right(self) -> float:
        xs = [p[0] for p in self.box if p]
        return max(xs) if xs else 0.0

    @property
    def height(self) -> float:
        return self.bottom - self.top


class OCRResult(BaseModel):
    """Normalized output of one OCR pass."""

    raw_text: str = ""
    normalized_text: str = ""
    lines: list[OCRLine] = Field(default_factory=list)
    confidence: float = 0.0
    boxes: list[list[list[float]]] = Field(default_factory=list)
    timestamp: float = 0.0
    error: str | None = None


class EmotionResult(BaseModel):
    label: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: str | None = None


class SuggestedReply(BaseModel):
    style: str
    text: str
    # Optional rationale: why this phrasing fits the situation.
    why: str = ""


class AnalysisResult(BaseModel):
    """Structured AI analysis. Core fields are fixed by the product spec.

    The extra fields are optional and backward compatible:
    - thinking:    concise, user-visible reasoning steps (fallback when the
                   provider does not stream a native reasoning channel);
    - evidence:    quoted text / visual cues that support the reading;
    - alternatives: at least one competing interpretation, to discourage
                   overconfident mind-reading;
    - vision_used: whether a screenshot was part of this request.
    """

    surface_meaning: str
    possible_intent: list[str]
    emotion: EmotionResult
    potential_needs: list[str]
    reply_strategy: str
    suggested_replies: list[SuggestedReply]
    uncertainty: str

    thinking: list[str] = []
    evidence: list[str] = []
    alternatives: list[str] = []
    vision_used: bool = False

    @field_validator(
        "possible_intent",
        "potential_needs",
        "thinking",
        "evidence",
        "alternatives",
        mode="before",
    )
    @classmethod
    def _coerce_str_to_list(cls, v):
        """Real models occasionally return a bare string for a list field
        (e.g. qwen3.7-plus returns possible_intent as one string). Normalize
        it to a single-element list instead of failing the whole analysis."""
        if isinstance(v, str):
            v = v.strip()
            return [v] if v else []
        return v

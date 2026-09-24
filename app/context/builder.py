"""Message segmentation & speaker heuristic.

V1 does not attempt perfect chat-bubble parsing. It groups OCR lines into
messages using vertical proximity + horizontal overlap, and labels the
speaker only when the bubble is clearly on the left ("对方") or right ("我")
of the region. Everything else stays "未知".
"""
from __future__ import annotations

from app.context.models import ContextMessage, SPEAKER_OTHER, SPEAKER_SELF
from app.models.schemas import OCRLine

LEFT_RATIO = 0.42   # message x_center <  42% of region width -> 对方
RIGHT_RATIO = 0.58  # message x_center >  58% of region width -> 我


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _horizontal_overlap_ratio(a: OCRLine, b: OCRLine) -> float:
    left = max(a.left, b.left)
    right = min(a.right, b.right)
    if right <= left:
        return 0.0
    overlap = right - left
    smaller = min(a.right - a.left, b.right - b.left)
    return overlap / smaller if smaller > 0 else 0.0


def _speaker_for(x_center: float, region_width: float, enabled: bool) -> tuple[str | None, str]:
    if not enabled or region_width <= 0:
        return None, "unknown"
    ratio = x_center / region_width
    if ratio < LEFT_RATIO:
        return SPEAKER_OTHER, "heuristic"
    if ratio > RIGHT_RATIO:
        return SPEAKER_SELF, "heuristic"
    return None, "unknown"


def segment_messages(
    lines: list[OCRLine],
    region_width: float,
    timestamp: float,
    speaker_heuristic: bool = True,
) -> list[ContextMessage]:
    """Group OCR lines into messages (sorted top-to-bottom, left-to-right)."""
    if not lines:
        return []

    ordered = sorted(
        lines,
        key=lambda ln: (ln.top, ln.left),
    )
    heights = [ln.height for ln in ordered if ln.height > 0]
    median_h = _median(heights) if heights else 12.0
    gap_threshold = max(10.0, median_h * 1.6)

    groups: list[list[OCRLine]] = []
    current: list[OCRLine] = []
    for line in ordered:
        if not current:
            current.append(line)
            continue
        last = current[-1]
        vertical_gap = line.top - last.bottom
        overlap = _horizontal_overlap_ratio(last, line)
        if vertical_gap <= gap_threshold and overlap >= 0.35:
            current.append(line)
        else:
            groups.append(current)
            current = [line]
    if current:
        groups.append(current)

    messages: list[ContextMessage] = []
    for group in groups:
        text = " ".join(ln.text.strip() for ln in group if ln.text.strip())
        if not text:
            continue
        xs = [ln.x_center for ln in group]
        x_center = sum(xs) / len(xs) if xs else region_width / 2
        speaker, source = _speaker_for(x_center, region_width, speaker_heuristic)
        messages.append(
            ContextMessage(
                content=text,
                speaker=speaker,
                timestamp=timestamp,
                speaker_source=source,
            )
        )
    return messages


def split_text_messages(text: str, timestamp: float) -> list[ContextMessage]:
    """Fallback segmentation for plain text (edited text / no boxes)."""
    messages: list[ContextMessage] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            messages.append(
                ContextMessage(content=line, speaker=None, timestamp=timestamp, speaker_source="unknown")
            )
    return messages

"""Local recognition of conversation panes, avatars and speaker labels."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import re

import numpy as np
from PIL import Image

from app.models.schemas import ChatAttribution, ConversationInfo, OCRLine, OCRResult
from app.ocr.normalize import normalize_text
from app.ocr.preprocess import preprocess


_COUNT = re.compile(r"[（(]\s*([1-9]\d{0,4})\s*(?:人)?[）)]\s*$")
_TIME = re.compile(r"^(?:(?:昨天|星期[一二三四五六日天]|周[一二三四五六日天]|\d{1,4}[年/.\-]\d{1,2}(?:[月/.\-]\d{1,2}日?)?)\s*)?\d{1,2}[:：]\d{2}(?:[:：]\d{2})?$")
_BADGE = re.compile(r"^(?:(?:LV\s*\d+\s*(?:群主|管理员)?|群主|管理员)\s*)+", re.I)
_GROUP = re.compile(r"(?:群聊|群成员|群公告|群文件|群主|群管理员)")


def _has_box(line) -> bool:
    return len(line.box) >= 2 and line.height > 0 and line.right > line.left


def _sidebar_edge(image: np.ndarray, lines) -> int | None:
    height, width = image.shape[:2]
    if width < 320 or height < 190:
        return None
    sample = image[height // 12:height * 5 // 6:4].astype(np.float32).mean(axis=2)
    positions = np.arange(width * 17 // 100, width * 47 // 100)
    prefix = np.pad(np.cumsum(sample, axis=1, dtype=np.float64), ((0, 0), (1, 0)))
    left_band = prefix[:, positions - 3] - prefix[:, positions - 8]
    right_band = prefix[:, positions + 8] - prefix[:, positions + 3]
    delta = (left_band - right_band) / 5
    support = np.maximum((delta >= 7).mean(axis=0), (delta <= -7).mean(axis=0))
    gradient = sample[:, positions - 1] - sample[:, positions]
    sharp_support = np.maximum((gradient >= 7).mean(axis=0), (gradient <= -7).mean(axis=0))
    candidates = (support >= 0.6) | (sharp_support >= 0.57)
    if not candidates.any():
        return None
    strength = np.minimum(36, np.abs(np.median(delta[:, candidates], axis=0)))
    boundary = np.minimum(24, np.abs(np.median(gradient[:, candidates], axis=0)))
    scores = support[candidates] * strength + boundary + 4 * sharp_support[candidates]
    edges = zip(scores, positions[candidates], sharp_support[candidates])
    for _, x, sharp_support in sorted(edges, reverse=True):
        left_rows = {int(line.top / 14) for line in lines if line.right <= x + 2}
        right_rows = {int(line.top / 14) for line in lines if line.left >= x - 2}
        crossing = sum(line.left < x - 4 < x + 4 < line.right for line in lines)
        if len(left_rows) >= 3 and crossing <= 1 and (len(right_rows) >= 2 or sharp_support >= .7):
            return int(x)
    return None


def _sidebar_selection(image: np.ndarray, lines, edge: int, title: str) -> str:
    sidebar = [line for line in lines if line.left >= edge * 0.13 and line.right < edge - 3
               and not _TIME.fullmatch(line.text.strip())]
    key = re.sub(r"\s+", "", _COUNT.sub("", title)).casefold()
    if key:
        for line in sidebar:
            if re.sub(r"\s+", "", line.text).casefold() == key:
                return line.text

    # A selected row usually has a uniform highlight across most of the list.
    # Search only the list, below the search box; use the first text in that row.
    area = image[:, edge // 6:edge * 4 // 5:3].astype(np.float32).mean(axis=2)
    row_level = np.median(area, axis=1)
    offset = min(75, max(25, image.shape[0] // 16))
    background = float(np.median(row_level[offset:]))
    changed = np.abs(row_level - background) >= 10
    changed[:offset] = False
    edges = np.flatnonzero(np.diff(np.r_[False, changed, False]))
    for start, end in zip(edges[::2], edges[1::2]):
        if 27 <= end - start <= 115:
            labels = [line for line in sidebar if start + 2 <= line.top < end - 10]
            if labels:
                return min(labels, key=lambda line: (line.top, line.left)).text
    return ""


def _panel_separators(image: np.ndarray, left: int) -> tuple[int, int]:
    height = image.shape[0]
    area = image[:, left + 5:-5:4].astype(np.float32).mean(axis=2)
    # Thin separators span the message pane. Text and bubble edges affect far
    # fewer columns and won't produce a strong whole-row contrast.
    rows = area[17:height - 4]
    changed = np.maximum(np.abs(rows - area[14:height - 7]),
                         np.abs(rows - area[20:height - 1]))
    candidates = np.flatnonzero((changed >= 5).mean(axis=1) >= .76) + 17
    bands = []
    for y in candidates:
        row = area[y]
        if np.percentile(row, 90) - np.percentile(row, 10) <= 14:
            if not bands or y - bands[-1] > 5:
                bands.append(int(y))
    top = max((y + 1 for y in bands if y <= min(105, height * 0.14)), default=0)
    bottom = next((y for y in bands if height * 0.38 <= y <= height * 0.92), height)
    return top, bottom


@dataclass(frozen=True)
class Avatar:
    side: str
    x: int
    y: int
    size: int
    key: str


@lru_cache(maxsize=1)
def _opencv():
    # PaddleOCR already installs OpenCV. Geometry-only attribution still works
    # for installations running an alternative OCR engine without OpenCV.
    try:
        import cv2
    except ImportError:
        return None
    return cv2


def _avatars(message_image: np.ndarray) -> list[Avatar]:
    cv2 = _opencv()
    height, width = message_image.shape[:2]
    if cv2 is None or min(height, width) < 80:
        return []
    band = min(110, width // 5)
    minimum = max(14, min(height, width) // 38)
    avatars = []
    for side, offset in (("left", 0), ("right", width - band)):
        strip = message_image[:, offset:offset + band]
        background = np.median(strip[::3, ::3], axis=(0, 1))
        mask = (np.max(np.abs(strip.astype(np.float32) - background), axis=2) >= 23).astype(np.uint8)
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for item in contours:
            x, y, w, h = cv2.boundingRect(item)
            if not (minimum <= min(w, h) and max(w, h) <= min(94, band - 2)):
                continue
            if min(w, h) < 0.7 * max(w, h) or cv2.contourArea(item) < 0.32 * w * h:
                continue
            distance = x if side == "left" else band - x - w
            if distance >= band // 2 or (side == "left" and x + w >= band - 1) or (side == "right" and x < 1):
                continue
            tile = strip[y:y + h, x:x + w]
            # A small grid distinguishes repeated avatars without retaining their images.
            tile = tile[h // 8:h - h // 8, w // 8:w - w // 8]
            grid = np.asarray(Image.fromarray(tile).resize((4, 4), Image.Resampling.BOX))
            key = (grid // 32).tobytes().hex()
            avatars.append(Avatar(side, offset + x, y, max(w, h), key))
    return sorted(avatars, key=lambda a: a.y)


def _aligned(line, avatar: Avatar, left: int) -> bool:
    if avatar.side == "left":
        offset = line.left - left - avatar.x - avatar.size
    else:
        offset = left + avatar.x - line.right
    return -5 <= offset <= max(54, 2 * avatar.size)


def _nickname(lines, indices, avatar, top: int):
    ordered = sorted(indices, key=lambda index: lines[index].top)
    first = lines[ordered[0]]
    heading = [index for index in ordered if lines[index].top <= first.top + max(4, first.height * .48)]
    following = next((lines[index] for index in ordered if index not in heading), None)
    parts = sorted((lines[index] for index in heading), key=lambda line: line.left)
    combined = " ".join(line.text for line in parts)
    name = _BADGE.sub("", combined).strip()
    badge = bool(_BADGE.match(combined))
    if not name or len(name) > 24 or re.search(r"[。！？?!，,：:\n]", name):
        return "", []
    if first.top - top > avatar.y + avatar.size * .58:
        return "", []
    if badge:
        return name, heading
    if (following is not None and first.height <= following.height * .91
            and -2 <= following.top - first.bottom <= max(28, avatar.size * .75)
            and abs(following.left - first.left) <= 28):
        return name, heading
    return "", []


def _media_in_view(image, avatars, lines, left, top):
    """Find large, non-text bubbles next to a detected avatar."""
    cv2 = _opencv()
    if cv2 is None or not avatars:
        return []
    height, width = image.shape[:2]
    base = np.median(image[::6, ::6], axis=(0, 1))
    mask = (np.max(np.abs(image.astype(np.float32) - base), axis=2) >= 30).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    additions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if min(w, h) < 43 or w >= width * .8 or h >= height * .6 or cv2.contourArea(contour) < w * h * .55:
            continue
        nearby = [avatar for avatar in avatars if -4 <= y - avatar.y <= avatar.size * 1.25
                  and (0 <= x - avatar.x - avatar.size <= avatar.size * 1.65 if avatar.side == "left"
                       else 0 <= avatar.x - x - w <= avatar.size * 1.65)]
        if not nearby:
            continue
        if any(_has_box(line) and x + left + 3 <= line.x_center <= x + left + w - 3
               and y + top + 3 <= (line.top + line.bottom) / 2 <= y + top + h - 3 for line in lines):
            continue
        x, y = x + left, y + top
        additions.append(OCRLine(text="〔图片或表情〕", confidence=.75,
                                 box=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]]))
    return additions


def _attribute(lines, avatars: list[Avatar], left: int, top: int, width: int):
    groups = defaultdict(list)
    plain = []
    for index, line in enumerate(lines):
        if _TIME.fullmatch(line.text.strip()):
            continue
        center_y = (line.top + line.bottom) / 2 - top
        candidates = [avatar for avatar in avatars if avatar.y - 8 <= center_y <= avatar.y + avatar.size * 3.1
                      and _aligned(line, avatar, left)]
        if candidates:
            groups[min(candidates, key=lambda avatar: abs(center_y - avatar.y - avatar.size * 0.45))].append(index)
        else:
            # Unanchored rows keep a tentative side only near a conversation edge.
            if line.left - left <= width * 0.22 and line.right - left <= width * 0.69:
                plain.append((index, "left"))
            elif line.right - left >= width * 0.78 and line.left - left >= width * 0.31:
                plain.append((index, "right"))
    result = list(lines)
    anchored = []
    for avatar, indices in groups.items():
        name, nickname_indices = _nickname(lines, indices, avatar, top)
        anchored.append((avatar, name))
        for index in indices:
            chat = ChatAttribution(side=avatar.side, avatar=avatar.key, nickname=name,
                                   is_nickname=index in nickname_indices)
            result[index] = lines[index].model_copy(update={"chat": chat})
    # Only infer sides without avatar anchors once a chat layout was actually found.
    if groups or left:
        for index, side in plain:
            result[index] = lines[index].model_copy(update={"chat": ChatAttribution(side=side)})
    return result, anchored


def _conversation(title: str, header_text: str, anchored, has_sidebar: bool) -> ConversationInfo:
    count = _COUNT.search(title) if title else None
    bare_title = title[:count.start()].strip() if count else title
    left_avatars = {avatar.key for avatar, _ in anchored if avatar.side == "left"}
    left_names = {name for avatar, name in anchored if avatar.side == "left" and name}
    if (count and has_sidebar) or _GROUP.search(header_text):
        reason = "会话标题后显示成员人数" if count and has_sidebar else "会话标题区含群聊标记"
        return ConversationInfo(title=bare_title, kind="group", reason=reason)
    if len(left_avatars) > 1 and (len(left_names) > 1 or has_sidebar):
        return ConversationInfo(title=bare_title, kind="group", reason="同侧识别到多个独立发言者")
    if re.search(r"好友|私聊|单聊", header_text):
        return ConversationInfo(title=bare_title, kind="private", reason="会话标题区含私聊标记")
    if has_sidebar and bare_title and len(left_avatars) == 1 and any(avatar.side == "right" for avatar, _ in anchored):
        return ConversationInfo(title=bare_title, kind="private", reason="当前可见画面仅有两侧各一位发言者", tentative=True)
    return ConversationInfo(title=bare_title, kind="unknown")


def recognize_chat_layout(result: OCRResult, frame, *, known_bounds=None) -> OCRResult:
    """Interpret the current capture locally; keep OCR-only crops usable."""
    if frame is None or not result.lines:
        return result
    image = preprocess(frame)
    height, width = image.shape[:2]
    lines = [line for line in result.lines if _has_box(line)]
    if not lines:
        return result
    left = _sidebar_edge(image, lines) or 0
    if not left and known_bounds:
        left = round(known_bounds[0] * width)
        top = round(known_bounds[1] * height)
        bottom = round(known_bounds[3] * height)
    else:
        top, bottom = _panel_separators(image, left) if left else (0, height)
    header = [line for line in lines if line.left >= left + 5 and line.top < (top or min(40, height * .08))]
    title = min(header, key=lambda line: (line.left, line.top)).text.strip() if left and header else ""
    if left and not top and header:
        top = min(int(max(line.bottom for line in header)) + 3, int(height * .14))
    visible = list(result.lines)
    if left:
        visible = [line for line in visible if not _has_box(line) or
                   (line.left >= left - 3 and top <= (line.top + line.bottom) / 2 < bottom)]
    pane = image[top:bottom, left:]
    avatars = _avatars(pane)
    media = _media_in_view(pane, avatars, visible, left, top)
    if media:
        visible = sorted(visible + media, key=lambda line: (line.top, line.left))
    active_sidebar = _sidebar_selection(image, lines, left, title) if left else ""
    visible, anchored = _attribute(visible, avatars, left, top, width - left)
    chat = _conversation(title or active_sidebar, " ".join(line.text for line in header) if left else "", anchored, bool(left))
    if active_sidebar:
        chat = chat.model_copy(update={"sidebar_selected": active_sidebar})
    if chat.kind == "private" and chat.title:
        for index, line in enumerate(visible):
            speaker = line.chat
            if speaker and speaker.side == "left" and speaker.avatar and not speaker.nickname:
                visible[index] = line.model_copy(update={
                    "chat": speaker.model_copy(update={"nickname": chat.title}),
                })
    raw = "\n".join(line.text for line in visible)
    return result.model_copy(update={"lines": visible, "raw_text": raw, "normalized_text": normalize_text(raw),
                                     "boxes": [line.box for line in visible], "conversation": chat,
                                     "chat_bounds": (left / width, top / height, 1.0, bottom / height) if left else None})


def crop_chat_frame(image, bounds):
    if image is None or not bounds:
        return image
    height, width = image.shape[:2]
    x1, y1, x2, y2 = bounds
    return image[int(y1 * height):round(y2 * height), int(x1 * width):round(x2 * width)]


def labeled_lines(lines) -> list[str]:
    """Resolve visible names across scroll pages and keep ambiguous speakers explicit."""
    aliases = defaultdict(set)
    anonymous = {}
    output = []
    for line in lines:
        chat = line.chat
        if chat and chat.avatar and chat.nickname:
            aliases[(chat.side, chat.avatar)].add(chat.nickname)
    for line in lines:
        chat = line.chat
        if chat is None:
            output.append(line.text)
            continue
        if chat.is_nickname:
            output.append("")
            continue
        known = aliases.get((chat.side, chat.avatar), set())
        if chat.nickname:
            label = chat.nickname
        elif len(known) == 1:
            label = next(iter(known))
        elif chat.avatar:
            index = anonymous.setdefault((chat.side, chat.avatar), len(anonymous) + 1)
            label = f"参与者{index}（{'左侧' if chat.side == 'left' else '右侧'}）"
        else:
            label = "左侧发言者" if chat.side == "left" else "右侧发言者"
        output.append(f"{label}：{line.text}")
    return output

"""Order-preserving stitching of scrolling OCR pages into one transcript.

Why this module exists
----------------------
The v2 product captures one screenshot at a time. As soon as the user scrolls
a long chat, consecutive screenshots share a block of *already read* lines and
add new ones above or below that block. Naively appending every line duplicates
whole blocks; naive "last N lines == first N lines" exact matching fails on a
single OCR typo.

Stitching unit: one OCR **visual line**, not one chat message. PaddleOCR splits
a wrapped bubble into several lines; re-grouping them into messages is
unreliable and would make coordinates meaningless. Line level is stable.

Alignment has two independent signals:

1. **Text similarity** - tolerant to a few wrong characters (difflib ratio over
   aggressively normalized text), so one OCR mistake does not break a 6-line
   overlap.
2. **Geometry** - for every matched pair the vertical offset ``page_y - doc_y``
   must be (almost) constant, and the horizontal offset must agree too. A page
   is a rigid translation of the document, so this is a hard constraint.

Geometry is what keeps genuinely repeated short lines apart. In a real chat
"好的" may appear five times; text alone cannot tell which copy belongs where,
but the offset and x-alignment of each copy can.

Only pairs that are ``i``-monotone and ``j``-monotone (a local alignment, like
Smith-Waterman over lines) can enter a block, so order can never be invented.
When no reliable block exists the page is still kept - inserted at the current
anchor with an explicit breakpoint marker - so no content is silently dropped
and the user can scroll back to fill the hole.

Public API
----------
- :func:`match_key` / :func:`line_similarity` - normalization + tolerant compare
- :func:`make_page_line` / :func:`page_lines_from_ocr` - OCR -> page lines
- :class:`TranscriptStitcher` - ``add_page()`` repeatedly, ``document.text()``
"""
from __future__ import annotations

import difflib
import logging
import math
import statistics
from dataclasses import dataclass, field

from app.analysis.chat_layout import labeled_lines
from app.models.schemas import ChatAttribution, OCRResult
from app.ocr.normalize import normalize_line

logger = logging.getLogger("ocr_chat.stitch")

# ---------------------------------------------------------------------------
# Tuning constants (all in "line units" unless stated otherwise)
# ---------------------------------------------------------------------------

#: At or below this many effective characters a line is treated as generic
#: ("好的", "嗯", "在吗"). Such a line only matches when it is *identical*;
#: fuzzy matching on a two-character reply is almost always a false positive.
#: Three characters already carry enough signal for the similarity threshold,
#: and even one wrong character there scores below 0.72 anyway.
SHORT_LINE_CHARS = 2

#: Cost of skipping one line on either axis inside the local alignment. High
#: enough that two generic lines separated by a few lines are not glued
#: together, low enough to survive one OCR-dropped line inside an overlap.
GAP_PENALTY = 1.6

#: A single-line block is only trusted when it carries at least this many
#: effective characters (a unique long sentence is a strong anchor).
SINGLE_LINE_MIN_CHARS = 20


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def match_key(text: str) -> str:
    """Normalize a line into its *matching* form (never used for display).

    - ``normalize_line`` already does NFKC, whitespace collapsing, border-noise
      stripping and repeated-punctuation collapsing;
    - all remaining whitespace is removed: in CJK a stray space is OCR noise;
    - ASCII is case-folded so "OK" and "ok" compare equal.
    """
    norm = normalize_line(str(text or ""))
    norm = "".join(ch for ch in norm if not ch.isspace())
    return norm.casefold()


def effective_len(text: str) -> int:
    """Count characters that carry meaning (alnum incl. CJK); punctuation not."""
    return sum(1 for ch in text if ch.isalnum())


def line_similarity(a: str, b: str) -> float:
    """Similarity of two *match keys* in ``[0, 1]``.

    ``difflib.SequenceMatcher`` is exact-order based and tolerates a couple of
    wrong characters, which is what we need for OCR noise. There is a cheap
    length pre-filter so the expensive ratio is only computed for plausible
    pairs (a page can contain thousands of candidate pairs).
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    longer = max(len(a), len(b))
    shorter = min(len(a), len(b))
    # A four-character difference on a ten-character line is not a typo.
    if longer - shorter > max(3, 0.35 * longer):
        return 0.0
    # Character-set overlap pre-filter: unrelated Chinese lines normally share
    # a few very common characters (我/你/的) but not most of them.
    sa, sb = set(a), set(b)
    if sa and sb:
        shared = len(sa & sb) / max(len(sa), len(sb))
        if shared < 0.45:
            return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


# ---------------------------------------------------------------------------
# Page lines (input side)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PageLine:
    """One OCR line of one screenshot, ready for alignment."""

    text: str            # display text (original punctuation kept)
    norm: str            # match_key(text)
    confidence: float = 0.0
    y: float = 0.0       # top coordinate inside the captured region (physical px)
    x: float = 0.0       # left coordinate
    height: float = 0.0
    has_geometry: bool = False
    chat: ChatAttribution | None = None


def make_page_line(
    text: str,
    *,
    confidence: float = 0.0,
    box=None,
    chat: ChatAttribution | None = None,
) -> PageLine | None:
    """Build a page line; returns ``None`` for blank / pure-noise lines."""
    display = str(text or "").strip()
    norm = match_key(display)
    if not norm or effective_len(norm) == 0:
        return None
    y = x = height = 0.0
    has_geo = False
    if box:
        try:
            xs = [float(p[0]) for p in box if p]
            ys = [float(p[1]) for p in box if p]
        except (TypeError, ValueError, IndexError):
            xs, ys = [], []
        if xs and ys:
            x = min(xs)
            y = min(ys)
            height = max(ys) - min(ys)
            has_geo = height > 0
    return PageLine(
        text=display,
        norm=norm,
        confidence=float(confidence or 0.0),
        y=y,
        x=x,
        height=height,
        has_geometry=has_geo,
        chat=chat,
    )


def page_lines_from_ocr(result: OCRResult | None) -> list[PageLine]:
    """Convert an OCRResult into page lines, preserving the engine's order.

    The engine already sorts lines by (top, left); re-sorting here would break
    results whose boxes are missing (all y == 0), so the order is kept as is.
    """
    if result is None:
        return []
    out: list[PageLine] = []
    for line in getattr(result, "lines", []) or []:
        pl = make_page_line(
            getattr(line, "text", ""),
            confidence=getattr(line, "confidence", 0.0),
            box=getattr(line, "box", None),
            chat=getattr(line, "chat", None),
        )
        if pl is not None:
            out.append(pl)
    return out


# ---------------------------------------------------------------------------
# Document lines (output side)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TranscriptLine:
    """One finalized line of the transcript."""

    uid: int                     # stable id; breakpoints point at it
    text: str
    norm: str
    confidence: float = 0.0
    y: float = 0.0
    x: float = 0.0
    height: float = 0.0
    has_geometry: bool = False
    first_page: int = 0
    occurrences: int = 1
    corrected: int = 0           # times a higher-confidence variant replaced text
    chat: ChatAttribution | None = None

    def observe(self, other: PageLine, dy: float | None = None) -> None:
        """Merge a second sighting of the same line.

        The variant with the higher OCR confidence wins, which naturally
        repairs a typo once a cleaner frame of the same line is captured.
        Coordinates are adopted only when the document line had none (it came
        from a breakpoint segment, where coordinates are guesses). ``dy`` is the
        rigid offset of *this* page, so the adopted value is converted back into
        document space; without it a repaired line would end up in page
        coordinates and poison every later geometric comparison.
        """
        self.occurrences += 1
        if other.chat and (self.chat is None
                           or (other.chat.avatar and not self.chat.avatar)
                           or (other.chat.avatar == self.chat.avatar and other.chat.nickname and not self.chat.nickname)):
            self.chat = other.chat
        if other.has_geometry and not self.has_geometry and dy is not None:
            self.y = other.y - dy
            self.x = other.x
            self.height = other.height
            self.has_geometry = True
        if other.confidence > self.confidence + 0.02 and other.text != self.text:
            self.text = other.text
            self.norm = other.norm
            self.confidence = other.confidence
            self.corrected += 1
        elif other.confidence > self.confidence:
            self.confidence = other.confidence


@dataclass(slots=True)
class Breakpoint:
    """A place where the transcript may be missing lines.

    ``before_uid`` is the uid of the document line the breakpoint sits in front
    of; ``None`` means "at the very end". Using a uid (not an index) keeps the
    marker correct after later insertions shift indices.
    """

    before_uid: int | None
    reason: str
    page: int
    direction: int = 1


@dataclass(slots=True)
class MergeReport:
    """What one page did to the document (used by the UI, logs and tests)."""

    kind: str                    # initial | merged | noop | break | empty
    page: int
    matched_lines: int = 0
    matched_chars: int = 0
    inserted_before: int = 0
    inserted_middle: int = 0
    inserted_after: int = 0
    score: float = 0.0
    direction: int = 1
    breakpoint: bool = False
    reason: str = ""
    resolved_breakpoints: int = 0   # breakpoints this page proved continuous


@dataclass(slots=True)
class _Block:
    """A local alignment candidate."""

    pairs: list[tuple[int, int]]   # (page index, document index), monotone
    dy: float | None               # vertical offset page_y - doc_y (median)
    score: float
    matched_chars: int
    inliers: int                   # pairs that agree on the rigid translation


# ---------------------------------------------------------------------------
# The stitcher
# ---------------------------------------------------------------------------

class TranscriptStitcher:
    """Merge scrolling pages into one ordered transcript.

    Typical use::

        stitcher = TranscriptStitcher()
        for page in pages:                       # each page = page_lines_from_ocr(...)
            stitcher.add_page(page, direction=+1)
        text = stitcher.text()

    ``direction`` is ``+1`` when the user scrolled down (new messages appear at
    the bottom, the document tail is extended) and ``-1`` when the user scrolled
    up (history appears at the top). It only matters when no overlap can be
    found: it decides on which side of the anchor the orphan page is parked.
    """

    def __init__(
        self,
        *,
        match_threshold: float = 0.72,
        min_overlap_lines: int = 2,
        min_overlap_chars: int = 12,
        search_radius: int = 80,
    ) -> None:
        self.match_threshold = max(0.5, min(0.98, float(match_threshold)))
        self.min_overlap_lines = max(1, int(min_overlap_lines))
        self.min_overlap_chars = max(4, int(min_overlap_chars))
        self.search_radius = max(12, int(search_radius))

        self.lines: list[TranscriptLine] = []
        self.breakpoints: list[Breakpoint] = []
        self.last_report: MergeReport | None = None

        self._uid = 0
        self._page_index = 0
        self._cursor = 0        # document index just past the last page's bottom
        self._top = 0           # document index of the last page's first line
        self._counts = {"pages": 0, "merged": 0, "noop": 0, "break": 0, "empty": 0}
        self._sim_cache: dict[tuple[str, str], float] = {}

    # ------------------------------------------------------------------ input
    def add_page(
        self,
        page: list[PageLine],
        *,
        direction: int = 1,
        timestamp: float = 0.0,
    ) -> MergeReport:
        """Merge one page; always returns a report (never raises on bad data)."""
        direction = -1 if int(direction) < 0 else 1
        page_index = self._page_index
        self._page_index += 1
        self._counts["pages"] += 1

        if not page:
            report = MergeReport(kind="empty", page=page_index, direction=direction)
            self._counts["empty"] += 1
            self.last_report = report
            return report

        if not self.lines:
            self._append_initial(page, page_index)
            report = MergeReport(
                kind="initial",
                page=page_index,
                matched_lines=len(page),
                matched_chars=sum(effective_len(p.norm) for p in page),
                inserted_after=len(page),
                direction=direction,
            )
            self._counts["merged"] += 1
            self.last_report = report
            logger.debug("stitch: initial page with %d lines", len(page))
            return report

        block = self._find_block(page)
        if block is None:
            report = self._insert_orphan_page(page, page_index, direction)
            self._counts["break"] += 1
            self.last_report = report
            return report

        report = self._merge_block(page, block, page_index, direction)
        if report.kind == "noop":
            self._counts["noop"] += 1
        else:
            self._counts["merged"] += 1
        self.last_report = report
        return report

    # --------------------------------------------------------------- internals
    def _next_uid(self) -> int:
        self._uid += 1
        return self._uid

    def _append_initial(self, page: list[PageLine], page_index: int) -> None:
        """First page: no alignment possible, take it verbatim with dy = 0."""
        for pl in page:
            self.lines.append(self._make_line(pl, dy=0.0, page_index=page_index))
        self._cursor = len(self.lines)
        self._top = 0

    def _make_line(self, pl: PageLine, dy: float | None, page_index: int) -> TranscriptLine:
        geometry = bool(pl.has_geometry and dy is not None)
        return TranscriptLine(
            uid=self._next_uid(),
            text=pl.text,
            norm=pl.norm,
            confidence=pl.confidence,
            y=(pl.y - dy) if geometry else 0.0,
            x=pl.x if geometry else 0.0,
            height=pl.height if geometry else 0.0,
            has_geometry=geometry,
            first_page=page_index,
            chat=pl.chat,
        )

    # ---- alignment ---------------------------------------------------------

    def _pair_similarity(self, a: PageLine, b: TranscriptLine) -> float:
        key = (a.norm, b.norm)
        cached = self._sim_cache.get(key)
        if cached is not None:
            return cached
        sim = line_similarity(a.norm, b.norm)
        # Bound the cache: transcripts are long-lived but repeated lines
        # ("好的") are what actually need caching.
        if len(self._sim_cache) > 40000:
            self._sim_cache.clear()
        self._sim_cache[key] = sim
        return sim

    def _gain(self, a: PageLine, b: TranscriptLine) -> float:
        """Alignment reward for a pair; 0 means "not a usable match".

        The reward is length-weighted but steeply quality-weighted (``sim^3``).
        That matters when a chat repeats a *template* ("周三咖啡店见，我大概3点
        到") many times: a 12-line block of mediocre 0.8 matches must not beat a
        6-line block of exact matches, or the document would silently shift a
        whole screen.
        """
        if a.chat and b.chat and a.chat.avatar and b.chat.avatar:
            if (a.chat.side != b.chat.side or a.chat.is_nickname != b.chat.is_nickname
                    or (a.chat.nickname and b.chat.nickname and a.chat.nickname != b.chat.nickname)):
                return 0.0
        len_a = effective_len(a.norm)
        len_b = effective_len(b.norm)
        if a.norm == b.norm:
            # Identical text is always allowed, including generic short lines.
            if len_a == 0:
                return 0.0
            return 1.0 + 0.5 * min(len_a, 24)
        # Generic short lines must be identical: "好的" vs "好" is not evidence.
        if min(len_a, len_b) <= SHORT_LINE_CHARS:
            return 0.0
        sim = self._pair_similarity(a, b)
        if sim < self.match_threshold:
            return 0.0
        return (sim ** 3) * (1.0 + 0.5 * min(len_a, len_b, 24))

    def _align(self, page: list[PageLine], lo: int, hi: int) -> tuple[list[tuple[int, int]], float]:
        """Local (Smith-Waterman style) alignment of a page against doc[lo:hi].

        Returns monotone pairs and their score. Gaps are allowed on both axes
        so a single OCR-dropped line inside an overlap does not split the block;
        the linear gap cost keeps scattered matches from being glued together.
        """
        m = len(page)
        n = hi - lo
        if m == 0 or n <= 0:
            return [], 0.0

        # H[i][j]: best score using page[:i] and doc[lo:lo+j].
        H = [[0.0] * (n + 1) for _ in range(m + 1)]
        # back: 1 = diagonal match, 2 = page line skipped, 3 = doc line skipped
        back = [[0] * (n + 1) for _ in range(m + 1)]
        best_v, best_i, best_j = 0.0, 0, 0

        for i in range(1, m + 1):
            pl = page[i - 1]
            row = H[i]
            prev = H[i - 1]
            brow = back[i]
            for j in range(1, n + 1):
                gain = self._gain(pl, self.lines[lo + j - 1])
                diag = prev[j - 1] + gain if gain > 0.0 else -1e9
                up = prev[j] - GAP_PENALTY
                left = row[j - 1] - GAP_PENALTY
                if diag >= up and diag >= left:
                    value, mark = diag, 1
                elif up >= left:
                    value, mark = up, 2
                else:
                    value, mark = left, 3
                if value <= 0.0:          # local alignment restarts here
                    value, mark = 0.0, 0
                row[j] = value
                brow[j] = mark
                if value > best_v:
                    best_v, best_i, best_j = value, i, j

        pairs: list[tuple[int, int]] = []
        i, j = best_i, best_j
        while i > 0 and j > 0:
            mark = back[i][j]
            if mark == 0:
                break
            if mark == 1:
                pairs.append((i - 1, lo + j - 1))
                i -= 1
                j -= 1
            elif mark == 2:      # the page line was skipped (new content)
                i -= 1
            else:                # the document line was skipped
                j -= 1
        pairs.reverse()
        return pairs, best_v

    def _loose_match(self, a: PageLine, b: TranscriptLine) -> bool:
        """Slightly relaxed test used only at block edges and when de-duplicating.

        It exists for a *typo* on an already-read line, not for "vaguely similar
        sentence". A much lower bar would let a templated chat (many messages
        built from the same phrase) swallow genuinely new lines.
        """
        if a.norm == b.norm:
            return True
        la, lb = effective_len(a.norm), effective_len(b.norm)
        if min(la, lb) <= SHORT_LINE_CHARS:
            return False
        return self._pair_similarity(a, b) >= max(0.68, self.match_threshold - 0.05)

    def _extend(
        self,
        page: list[PageLine],
        pairs: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """Grow a block outward while adjacent lines still match loosely.

        This is what stops a boundary typo from turning an already-read line
        into a "new" duplicate line.
        """
        if not pairs:
            return pairs
        first_i, first_j = pairs[0]
        last_i, last_j = pairs[-1]
        while first_i > 0 and first_j > 0 and self._loose_match(
            page[first_i - 1], self.lines[first_j - 1]
        ):
            first_i -= 1
            first_j -= 1
            pairs.insert(0, (first_i, first_j))
        while (
            last_i + 1 < len(page)
            and last_j + 1 < len(self.lines)
            and self._loose_match(page[last_i + 1], self.lines[last_j + 1])
        ):
            last_i += 1
            last_j += 1
            pairs.append((last_i, last_j))
        return pairs

    def _geometry(
        self,
        page: list[PageLine],
        pairs: list[tuple[int, int]],
    ) -> tuple[int, float | None, int]:
        """Check the rigid-translation assumption.

        Returns ``(inliers, dy, sample_count)``. ``dy`` is the median vertical
        offset ``page_y - doc_y`` over the inliers; ``sample_count`` is how many
        pairs had usable coordinates (below 2 nothing can be verified).

        A copy of "好的" that belongs elsewhere in the transcript usually differs
        by a full line height or more, so this rejects it.
        """
        samples = [
            (page[i].y - self.lines[j].y, page[i].x - self.lines[j].x, page[i].height)
            for i, j in pairs
            if page[i].has_geometry and self.lines[j].has_geometry
        ]
        if not samples:
            return 0, None, 0
        if len(samples) == 1:
            return 1, samples[0][0], 1

        heights = [s[2] for s in samples if s[2] > 0]
        tol_y = max(6.0, 0.45 * (statistics.median(heights) if heights else 20.0))
        tol_x = 16.0
        median_dy = statistics.median(s[0] for s in samples)
        median_dx = statistics.median(s[1] for s in samples)
        inlier_samples = [
            s for s in samples
            if abs(s[0] - median_dy) <= tol_y and abs(s[1] - median_dx) <= tol_x
        ]
        if inlier_samples:
            median_dy = statistics.median(s[0] for s in inlier_samples)
        # A rigid translation means *the same* offset for every line, not merely
        # offsets that share a median. With only two samples the median test is
        # vacuous (the midpoint is within tolerance of both), so check the
        # actual spread: two copies of "好的" one row apart must be rejected.
        if len(inlier_samples) >= 2:
            spread = max(s[0] for s in inlier_samples) - min(s[0] for s in inlier_samples)
            if spread > tol_y:
                return 0, None, len(samples)
        return len(inlier_samples), median_dy, len(samples)

    def _evaluate(
        self,
        page: list[PageLine],
        pairs: list[tuple[int, int]],
        score: float,
    ) -> _Block | None:
        """Apply the evidence rules and geometry consensus to a raw alignment."""
        if not pairs:
            return None
        pairs = self._extend(page, pairs)

        # Rigid-shift filter. Inside one page every line moves by the same
        # offset, so a pair that is off by a whole line height cannot be the
        # same message: it is a wrong copy of a repeated short line. Dropping
        # it turns that position into a "gap", where the slot/geometry rules
        # can still re-place it instead of trusting the text.
        offsets = [
            (i, j, page[i].y - self.lines[j].y, page[i].x - self.lines[j].x)
            for i, j in pairs
            if page[i].has_geometry and self.lines[j].has_geometry
        ]
        if len(offsets) >= 2:
            heights = [page[i].height for i, _, _, _ in offsets if page[i].height > 0]
            tol_y = max(6.0, 0.45 * (statistics.median(heights) if heights else 20.0))
            tol_x = 16.0
            med_y = statistics.median(o[2] for o in offsets)
            med_x = statistics.median(o[3] for o in offsets)
            bad = {
                (i, j) for i, j, dy_i, dx_i in offsets
                if abs(dy_i - med_y) > tol_y or abs(dx_i - med_x) > tol_x
            }
            if bad and len(pairs) - len(bad) >= 1:
                logger.debug("stitch: dropped %d off-shift pairs", len(bad))
                pairs = [p for p in pairs if p not in bad]

        matched_lines = len(pairs)
        matched_chars = sum(effective_len(page[i].norm) for i, _ in pairs)
        inliers, dy, sample_count = self._geometry(page, pairs)

        # If we have geometry, the overwhelming majority of *samples* must agree
        # with one rigid translation. Outliers are almost always wrong copies
        # of a repeated short line. One sample cannot verify anything, so the
        # rule only applies when at least two pairs carry coordinates.
        # The denominator is ``sample_count`` (pairs with coordinates), not
        # ``len(pairs)``: after a breakpoint the parked segment has no reliable
        # coordinates, and those pairs must not dilute the consensus of the
        # segment that does.
        if sample_count >= 2 and inliers < max(2, math.ceil(0.6 * sample_count)):
            logger.debug(
                "stitch: rejected block, geometry inliers %d/%d", inliers, sample_count
            )
            return None

        long_anchor = (
            matched_lines == 1 and matched_chars >= SINGLE_LINE_MIN_CHARS
        )
        # Short generic lines ("好的"/"嗯") are not evidence of their own: a
        # transcript repeats them, so any pair of them "matches" somewhere. A
        # usable block must therefore also contain one specific line (4+ chars).
        strong_pairs = sum(1 for i, _ in pairs if effective_len(page[i].norm) >= 4)
        normal_anchor = (
            matched_lines >= self.min_overlap_lines
            and strong_pairs >= 1
            and (matched_chars >= self.min_overlap_chars or inliers >= 2)
        )
        if not (long_anchor or normal_anchor):
            return None
        return _Block(
            pairs=pairs,
            dy=dy,
            score=score,
            matched_chars=matched_chars,
            inliers=inliers,
        )

    def _windows(self, doc_len: int, page_len: int) -> list[tuple[int, int]]:
        """Search windows: around the cursor, plus the head and the tail.

        The head/tail windows make history backfill and long jumps work without
        scanning the whole document on every frame.
        """
        span = max(self.search_radius, 3 * page_len, 24)
        windows = [
            (max(0, self._cursor - span), min(doc_len, self._cursor + span)),
            (0, min(doc_len, max(span, 3 * page_len))),
            (max(0, doc_len - max(span, 3 * page_len)), doc_len),
        ]
        unique: list[tuple[int, int]] = []
        for lo, hi in windows:
            lo = max(0, min(lo, doc_len))
            hi = max(lo, min(hi, doc_len))
            if hi - lo > 0 and (lo, hi) not in unique:
                unique.append((lo, hi))
        return unique

    def _find_block(self, page: list[PageLine]) -> _Block | None:
        """Best acceptable alignment for the page, or ``None`` (=> breakpoint)."""
        doc_len = len(self.lines)
        best: _Block | None = None
        best_rank = -1e9
        for lo, hi in self._windows(doc_len, len(page)):
            pairs, score = self._align(page, lo, hi)
            block = self._evaluate(page, pairs, score)
            if block is None:
                continue
            # Prefer strong evidence, and among equals the block nearest to the
            # previous page (scrolling is continuous 99% of the time).
            center = block.pairs[0][1]
            rank = block.score - 0.03 * abs(center - self._cursor)
            if rank > best_rank:
                best, best_rank = block, rank
        if best is not None:
            return best

        # Fallback: a jump far outside every window. Require stronger evidence
        # so a single common line cannot anchor the page to the wrong place.
        pairs, score = self._align(page, 0, doc_len)
        if len(pairs) >= 2:
            block = self._evaluate(page, pairs, score)
            if block is not None and block.matched_chars >= 2 * self.min_overlap_chars:
                logger.debug("stitch: matched via full-document fallback")
                return block
        return None

    # ---- grouping / de-duplication ----------------------------------------

    @staticmethod
    def _row_state(pl: PageLine, d: TranscriptLine, dy: float | None) -> int:
        """1 = same screen row, -1 = provably different rows, 0 = unknown."""
        if dy is None or not pl.has_geometry or not d.has_geometry:
            return 0
        if abs(pl.y - dy - d.y) <= 2.5 and abs(pl.x - d.x) <= 12.0:
            return 1
        return -1

    def _trim_before(self, lines: list[PageLine], at: int, dy: float | None = None, *, max_run: int = 8) -> list[PageLine]:
        """Drop a leading run that repeats the document lines just above ``at``.

        ``lines`` are about to be inserted *before* ``doc[at]``. If the page
        starts with the doc's last few lines (a one-line overlap on a fast
        scroll, or a whole already-read screen), those must not be stored twice.

        Coordinates are consulted when available: a repeated short line
        ("好的") is only a duplicate if it also sits on the *same row*. A new
        message always occupies a different row, so three consecutive "好的"
        are never collapsed into two.
        """
        best = 0
        limit = min(len(lines), at, max_run)
        for k in range(1, limit + 1):
            run = [(lines[i], self.lines[at - k + i]) for i in range(k)]
            if not all(self._loose_match(pl, d) for pl, d in run):
                continue
            rows = [self._row_state(pl, d, dy) for pl, d in run]
            if any(state < 0 for state in rows):
                continue
            if k == 1 and rows[0] == 0 and effective_len(run[0][0].norm) < 6:
                # A lone short line with no coordinates is not enough evidence:
                # trimming on it would silently delete real messages.
                continue
            best = k
        return lines[best:]

    def _trim_after(self, lines: list[PageLine], at: int, dy: float | None = None, *, max_run: int = 8) -> list[PageLine]:
        """Drop a trailing run that repeats the document lines starting at ``at``."""
        best = 0
        limit = min(len(lines), len(self.lines) - at, max_run)
        for k in range(1, limit + 1):
            run = [
                (lines[len(lines) - k + i], self.lines[at + i]) for i in range(k)
            ]
            if not all(self._loose_match(pl, d) for pl, d in run):
                continue
            rows = [self._row_state(pl, d, dy) for pl, d in run]
            if any(state < 0 for state in rows):
                continue
            if k == 1 and rows[0] == 0 and effective_len(run[0][0].norm) < 6:
                continue
            best = k
        return lines[: len(lines) - best]

    def _trim_gap(self, lines: list[PageLine], doc_lo: int, doc_hi: int) -> list[PageLine]:
        """Remove lines that duplicate document lines skipped *inside* a block.

        A gap in the local alignment means the page did not show that document
        line (typically one dropped OCR box). If the page *does* contain a fuzzy
        copy of it, inserting it would duplicate already-read content.
        """
        if doc_lo >= doc_hi or not lines:
            return lines
        kept: list[PageLine] = []
        cursor = doc_lo
        for pl in lines:
            hit = False
            for j in range(cursor, doc_hi):
                if self._loose_match(pl, self.lines[j]):
                    cursor = j + 1
                    hit = True
                    break
            if not hit:
                kept.append(pl)
        return kept

    def _repair_slots(
        self,
        lines: list[PageLine],
        dy: float | None,
        doc_lo: int,
        doc_hi: int,
    ) -> list[PageLine]:
        """Drop page lines that sit exactly on an existing document row.

        Text similarity is a weak signal for short lines ("好的" vs "好地" is
        one wrong character and half the string). Geometry is much stronger:
        inside a block the whole page is a rigid shift of the document, so a
        page line at ``doc_y + dy`` *is* that row of the chat window. When the
        text is close enough we also repair the stored copy, so a blurry first
        frame is fixed by the next clean one instead of duplicated.
        """
        if dy is None or not lines:
            return lines
        occupied: set[int] = set()
        kept: list[PageLine] = []
        for pl in lines:
            if not pl.has_geometry:
                kept.append(pl)
                continue
            hit = -1
            for j in range(max(0, doc_lo), min(doc_hi, len(self.lines))):
                if j in occupied:
                    continue
                d = self.lines[j]
                if not d.has_geometry:
                    continue
                if abs(pl.y - dy - d.y) <= 2.5 and abs(pl.x - d.x) <= 12.0:
                    hit = j
                    break
            if hit < 0:
                kept.append(pl)
                continue
            d = self.lines[hit]
            if line_similarity(pl.norm, d.norm) < 0.45:
                # Same screen row, unrelated text: the chat scrolled by a whole
                # line and a *different* message landed here. Keep it.
                kept.append(pl)
                continue
            occupied.add(hit)
            # Same row, related text: this is that message, misread. Keep the
            # better reading instead of storing a duplicate.
            d.observe(pl, dy)
            logger.debug(
                "stitch: %r collides with row %d; treated as the same line",
                pl.text, hit,
            )
        return kept

    def _plan_groups(
        self,
        page: list[PageLine],
        pairs: list[tuple[int, int]],
        dy: float | None = None,
    ) -> list[tuple[int, list[PageLine]]]:
        """Unmatched page lines grouped by where they belong in the document.

        Each group is ``(insert_before_doc_index, lines)``. Insertion happens
        *before* the given document index, so ``len(doc)`` means "append".
        Only the edges of each group are de-duplicated, so a genuinely repeated
        "好的" that sits in the middle of a group always survives.
        """
        groups: list[tuple[int, list[PageLine]]] = []
        prev_i = -1
        prev_j = -1
        # Rows are unique inside one viewport, so a page line can only collide
        # with a document line that sits within roughly one page height of the
        # insertion point. A wider window catches duplicates parked on the other
        # side of a breakpoint without scanning the whole transcript.
        window = len(page) + 4
        for i, j in pairs:
            if i > prev_i + 1:
                raw = page[prev_i + 1:i]
                at = j if prev_j < 0 else prev_j + 1
                raw = self._repair_slots(raw, dy, at - window, at + window)
                if prev_j >= 0:
                    raw = self._trim_gap(raw, prev_j + 1, j)
                raw = self._trim_before(raw, at, dy)
                raw = self._trim_after(raw, at, dy)
                if raw:
                    groups.append((at, raw))
            prev_i, prev_j = i, j
        if prev_i < len(page) - 1:
            raw = page[prev_i + 1:]
            at = prev_j + 1
            raw = self._repair_slots(raw, dy, at - window, at + window)
            raw = self._trim_before(raw, at, dy)
            raw = self._trim_after(raw, at, dy)
            if raw:
                groups.append((at, raw))
        return groups

    def _merge_block(
        self,
        page: list[PageLine],
        block: _Block,
        page_index: int,
        direction: int,
    ) -> MergeReport:
        pairs = block.pairs
        dy = block.dy
        groups = self._plan_groups(page, pairs, dy)
        old_len = len(self.lines)

        # A page that matched content on both sides of an existing breakpoint
        # has just *proved* continuity there: the seam is one rigid scroll, so
        # the marker must go. Breakpoints are keyed by the uid of their first
        # line, so resolve them against the document indices seen before the
        # rebuild.
        old_index = {line.uid: i for i, line in enumerate(self.lines)}
        lo_j, hi_j = pairs[0][1], pairs[-1][1]
        resolved: list[Breakpoint] = []
        for bp in self.breakpoints:
            if bp.before_uid is None:
                continue
            idx = old_index.get(bp.before_uid)
            if idx is not None and lo_j < idx <= hi_j:
                resolved.append(bp)
        if resolved:
            logger.info("stitch: page %d bridges %d breakpoint(s)", page_index, len(resolved))
            self.breakpoints = [bp for bp in self.breakpoints if bp not in resolved]

        # Bucket by "insert before old document index". Rebuilding the list in
        # one pass keeps every index consistent even with several holes.
        buckets: dict[int, list[PageLine]] = {}
        for at, lines in groups:
            buckets.setdefault(max(0, min(at, old_len)), []).extend(lines)

        # shift_at[j] = how many lines were inserted before old line j.
        shift_at: list[int] = []
        running = 0
        for j in range(old_len):
            if j in buckets:
                running += len(buckets[j])
            shift_at.append(running)

        new_lines: list[TranscriptLine] = []
        for k in range(old_len + 1):
            if k in buckets:
                for pl in buckets[k]:
                    new_lines.append(self._make_line(pl, dy, page_index))
            if k < old_len:
                new_lines.append(self.lines[k])
        self.lines = new_lines

        # Fold the new observations into the shifted matched lines: a cleaner
        # frame of the same line can repair an earlier typo.
        for i, j in pairs:
            shifted = j + shift_at[j]
            if 0 <= shifted < len(self.lines):
                self.lines[shifted].observe(page[i], dy)

        first_j = pairs[0][1] + shift_at[pairs[0][1]]
        last_j = pairs[-1][1] + shift_at[pairs[-1][1]]
        tail_len = sum(len(v) for k, v in buckets.items() if k > pairs[-1][1])
        self._cursor = min(len(self.lines), last_j + 1 + tail_len)
        self._top = first_j

        before = sum(len(v) for k, v in buckets.items() if k <= pairs[0][1])
        after = sum(len(v) for k, v in buckets.items() if k > pairs[-1][1])
        middle = sum(len(v) for v in buckets.values()) - before - after

        kind = "noop" if not groups else "merged"
        report = MergeReport(
            kind=kind,
            page=page_index,
            matched_lines=len(pairs),
            matched_chars=block.matched_chars,
            inserted_before=before,
            inserted_middle=middle,
            inserted_after=after,
            resolved_breakpoints=len(resolved),
            score=block.score,
            direction=direction,
        )
        if kind == "noop":
            logger.debug("stitch: page %d already read (no new lines)", page_index)
        else:
            logger.debug(
                "stitch: page %d matched %d lines, +%d new (before %d / after %d)",
                page_index, len(pairs), before + middle + after, before, after,
            )
        return report

    def _insert_orphan_page(
        self,
        page: list[PageLine],
        page_index: int,
        direction: int,
    ) -> MergeReport:
        """No reliable overlap: keep the page, mark a breakpoint.

        Downward jumps are parked at the cursor (below the last read line);
        upward jumps are parked just above the previous page's top, which is the
        best guess available without any anchor. The parked lines deliberately
        keep *no* coordinates (``dy=None``): without an anchor the jump height is
        unknown, so their screen positions are not document positions.
        """
        at = max(0, min(self._top if direction < 0 else self._cursor, len(self.lines)))

        # Even without a trustworthy block, an overlap at the edge is common on
        # fast scrolls. Trim it so the same line is not stored twice.
        page_lines = self._trim_before(page, at)
        page_lines = self._trim_after(page_lines, at)
        if not page_lines:
            logger.debug(
                "stitch: page %d had no block but was already fully present", page_index
            )
            self._cursor = at
            self._top = at
            return MergeReport(kind="noop", page=page_index, direction=direction)

        new_lines = [
            # ``dy=None`` means "coordinates unknown on purpose": the parked
            # segment's screen positions are a guess (we never knew the jump
            # height), so pretending they are document coordinates would make
            # every later geometric comparison reject the page that repairs
            # this hole. Text still anchors this segment; geometry is restored
            # the first time a bridging page re-observes the line.
            self._make_line(pl, dy=None, page_index=page_index) for pl in page_lines
        ]
        self.lines[at:at] = new_lines
        # The marker belongs *in front of* this block, so it is attached to the
        # block's own first line. A uid (not an index) survives later insertions.
        self.breakpoints.append(
            Breakpoint(
                before_uid=new_lines[0].uid,
                reason="与已读内容没有可靠重叠（可能快速跳页或漏采）",
                page=page_index,
                direction=direction,
            )
        )
        self._top = at
        self._cursor = at + len(new_lines)
        logger.info(
            "stitch: page %d has no reliable overlap; breakpoint at line %d (+%d lines)",
            page_index, at, len(new_lines),
        )
        return MergeReport(
            kind="break",
            page=page_index,
            inserted_after=len(new_lines),
            direction=direction,
            breakpoint=True,
            reason="no reliable overlap",
        )

    # ---------------------------------------------------------------- output
    @property
    def page_count(self) -> int:
        return self._counts["pages"]

    @property
    def stats(self) -> dict:
        return {
            **self._counts,
            "lines": len(self.lines),
            "breakpoints": len(self.breakpoints),
        }

    @property
    def text_lines(self) -> list[str]:
        """Transcript lines only (no breakpoint markers)."""
        return [line.text for line in self.lines]

    def marker_text(self, number: int, bp: Breakpoint) -> str:
        """Human-readable breakpoint line placed inside the transcript."""
        return f"〔断点 {number} · {bp.reason}，建议向上滚动补采〕"

    def text(self, *, include_breakpoints: bool = True, include_speakers: bool = False) -> str:
        """Render the transcript; breakpoints become visible marker lines."""
        rendered = labeled_lines(self.lines) if include_speakers else self.text_lines
        if not include_breakpoints:
            return "\n".join(line for line in rendered if line)
        by_uid: dict[int | None, list[Breakpoint]] = {}
        for bp in self.breakpoints:
            by_uid.setdefault(bp.before_uid, []).append(bp)
        parts: list[str] = []
        number = 0
        for line, display in zip(self.lines, rendered):
            for bp in by_uid.get(line.uid, []):
                number += 1
                parts.append(self.marker_text(number, bp))
            if display:
                parts.append(display)
        for bp in by_uid.get(None, []):
            number += 1
            parts.append(self.marker_text(number, bp))
        return "\n".join(parts)

    def reset(self) -> None:
        self.lines.clear()
        self.breakpoints.clear()
        self.last_report = None
        self._uid = 0
        self._page_index = 0
        self._cursor = 0
        self._top = 0
        self._counts = {"pages": 0, "merged": 0, "noop": 0, "break": 0, "empty": 0}
        self._sim_cache.clear()


def stitch_pages(
    pages: list[list[PageLine]],
    *,
    directions: list[int] | None = None,
    **kwargs,
) -> TranscriptStitcher:
    """Convenience helper: stitch a list of pages and return the stitcher."""
    stitcher = TranscriptStitcher(**kwargs)
    for index, page in enumerate(pages):
        direction = directions[index] if directions and index < len(directions) else 1
        stitcher.add_page(page, direction=direction)
    return stitcher

"""Synthetic chat transcripts + scrolling viewports + stitching metrics.

The generator reproduces the *structure* of a real chat window, not pixel art:

- a ground-truth list of visual lines (speaker + text, some repeated short
  replies, some long sentences);
- a viewport that shows ``size`` consecutive lines at a regular pitch;
- sub-line scroll offsets and optional OCR noise;
- a scorer with fuzzy line matching, so one wrong character is not counted as
  a missing line.

Everything is deterministic (seeded), so the reported numbers are comparable
between runs and between algorithm variants.
"""
from __future__ import annotations

import random
import time

from app.analysis.stitch import (
    TranscriptStitcher,
    line_similarity,
    make_page_line,
    match_key,
)

PITCH = 22.0
LINE_H = 18.0

_SHORT = ["好的", "嗯", "收到", "在吗", "晚安", "可以"]

#: Hand-written, mutually distinct chat sentences. Real conversations rarely
#: repeat a whole sentence, and a generator built from one template ("周三我要
#: 去某地办第 N 件事") would create *false* overlaps that no stitcher could
#: resolve from text alone — it would make the metric meaningless.
_LONG = [
    "刚才在地铁上碰到高中同学了，站着聊了七八分钟",
    "明天下午三点的评审改到四点半，会议室换到二楼",
    "你上次发的那个链接打不开了，还有别的入口吗",
    "我把发票拍照传群里了，你记得周五之前报销",
    "食堂今天的新窗口排了好长的队，味道也就那样",
    "电脑又蓝屏了，这次报的是内存条那条错误码",
    "我妈说下周要来住两天，我得把客房收拾出来",
    "论文的第三章导师看过了，让我把图表重新做一遍",
    "楼下超市的鸡蛋打折，我顺手买了两板回来",
    "周末的球局还缺一个人，你要是没事就过来",
    "这个月的电费比上个月多了将近一倍，空调开太狠",
    "地铁四号线今天又限流，我绕了一大圈才到公司",
    "帮我问一下前台，快递能不能放到保安室过夜",
    "上次借你的那本书我看完了，什么时候方便还给你",
    "体检报告出来了，除了血脂偏高别的都还正常",
    "手机屏幕摔裂了一个角，换屏要四百多块",
    "团建的日子定在下周六，地点还在选，你有推荐吗",
    "房东说下个月房租要涨两百，我打算跟他谈谈",
    "早上出门忘带工牌了，进楼的时候被拦了半小时",
    "那个项目的数据接口一直超时，我下午再测一轮",
    "冰箱里的酸奶过期了，你回来的时候顺手买一箱",
    "我今天可能要晚点回，客户那边临时加了需求",
    "楼下新装了充电桩，晚上车位终于不用抢了",
    "这周末有雨，爬山的事要不要往后挪一周",
    "老师把作业的提交时间放宽到周日晚上十二点",
    "我电脑的风扇声音特别大，估计得清一下灰",
    "会议纪要我整理好了，发你邮箱你抽空看一眼",
    "刚才物业来电话，说楼上漏水要上门检查",
    "你上次推荐的牙膏挺好用的，链接再发我一次",
    "银行那边说流水要打印纸质版，还得盖章",
    "孩子学校通知明天提前放学，你能去接一下吗",
    "我把旧手机里的照片都导到硬盘里了，腾出不少空间",
    "打印机又卡纸了，我把后面那张撕下来才发现",
    "这个月的报表格式改了，表头多了两列备注",
    "健身房年卡到期了，续费比去年贵了三百块",
    "中午那家面馆换老板了，味道跟以前完全不一样",
    "我在网上预约了周六上午的维修，师傅会上门",
    "宿舍的热水器坏了，报修说要等两天才来人",
    "刚看完那部电影，后半段节奏有点拖，但结局还行",
    "年会抽奖我什么都没中，就拿到一盒坚果",
    "你那份合同我看了，第六条的责任划分要改一下",
    "银行卡被限额了，转账超过五千要去柜台办理",
    "楼道的声控灯不亮了，晚上回去得用手机照路",
    "我把下周的行程排好了，周三周四都在外面跑",
    "这学期的课表调了两次，周一的课挪到周五下午",
]

#: Similar-looking substitutions: what a low-resolution OCR pass typically does.
_TYPO = {
    "的": "地", "地": "的", "吗": "嘛", "嘛": "吗", "我": "俄", "你": "尔",
    "是": "事", "在": "再", "说": "悦", "会": "全", "时": "对", "就": "旧",
}


def build_transcript(count: int = 60, seed: int = 5) -> list[str]:
    """Return a deterministic, chat-like ground-truth line list.

    Structure: mostly unique sentences, plus generic short replies and
    deliberate ``好的`` pairs. Every unique sentence is used at most once and
    the result is checked for accidental near-duplicates, so a "miss" in the
    metrics can only come from the stitcher, never from the fixture.
    """
    rng = random.Random(seed)
    pool = list(_LONG)
    rng.shuffle(pool)
    used = 0
    lines: list[str] = []
    for i in range(count):
        speaker = "甲" if i % 2 == 0 else "乙"
        if i % 11 == 4 or i % 11 == 5:
            # Two consecutive generic replies; must NOT be collapsed by stitching.
            lines.append("好的")
            continue
        if i % 7 == 3:
            lines.append(rng.choice(_SHORT))
            continue
        if used >= len(pool):
            raise AssertionError(
                f"transcript of {count} lines needs more than {len(pool)} sentences"
            )
        body = pool[used]
        used += 1
        text = f"{speaker}：{body}"
        # Safety net: unrelated lines must not look like an overlap.
        for earlier in lines:
            if line_similarity(match_key(text), match_key(earlier)) >= 0.7:
                raise AssertionError(f"generated near-duplicate: {text!r} / {earlier!r}")
        lines.append(text)
    return lines


def add_noise(text: str, rng: random.Random, rate: float) -> str:
    """Substitute at most one character, as a single OCR misread would."""
    if rate <= 0.0 or rng.random() > rate:
        return text
    chars = list(text)
    for _ in range(3):
        index = rng.randrange(len(chars))
        if chars[index] in _TYPO:
            chars[index] = _TYPO[chars[index]]
            return "".join(chars)
    # No mappable character: drop a trailing punctuation mark instead.
    if chars and chars[-1] in "。！？!?，,":
        chars.pop()
    return "".join(chars)


def make_page(
    truth: list[str],
    start: int,
    size: int,
    *,
    offset: float = 0.0,
    noise: float = 0.0,
    rng: random.Random | None = None,
    x: float = 10.0,
):
    """Render one viewport of the transcript as page lines with OCR boxes."""
    lines = []
    for i in range(size):
        index = start + i
        if index < 0 or index >= len(truth):
            continue
        text = truth[index]
        confidence = 0.92
        if noise and rng is not None:
            noisy = add_noise(text, rng, noise)
            if noisy != text:
                confidence = 0.55
            text = noisy
        top = offset + i * PITCH
        box = [
            [x, top],
            [x + 260.0, top],
            [x + 260.0, top + LINE_H],
            [x, top + LINE_H],
        ]
        pl = make_page_line(text, confidence=confidence, box=box)
        if pl is not None:
            lines.append(pl)
    return lines


def scroll_pages(
    truth: list[str],
    starts: list[int],
    view: int,
    *,
    noise: float = 0.0,
    seed: int = 0,
    subline: bool = True,
):
    """Build one page per scroll position, with varying sub-line offsets."""
    rng = random.Random(seed)
    pages = []
    for i, start in enumerate(starts):
        offset = float((i * 7) % int(PITCH)) if subline else 0.0
        pages.append(
            make_page(truth, start, view, offset=offset, noise=noise, rng=rng)
        )
    return pages


def _fuzzy_equal(a: str, b: str, threshold: float = 0.82) -> bool:
    return line_similarity(match_key(a), match_key(b)) >= threshold


def _lcs_matched(output: list[str], truth: list[str]) -> int:
    """Longest common subsequence under fuzzy line equality."""
    n, m = len(output), len(truth)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if _fuzzy_equal(output[i - 1], truth[j - 1]):
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]


def _assign_positions(output: list[str], truth: list[str]) -> list[int]:
    """Map each output line to the most plausible truth index.

    Ties (repeated "好的") are broken toward the expected position, derived from
    the median offset between the output index and the matched truth index.
    This is what makes the order metric meaningful for transcripts that contain
    genuinely duplicated short replies.
    """
    candidates: list[list[int]] = []
    for line in output:
        candidates.append([j for j, t in enumerate(truth) if _fuzzy_equal(line, t)])

    # First pass: plain index proximity gives the typical offset.
    offsets: list[int] = []
    for i, cands in enumerate(candidates):
        if not cands:
            continue
        j = min(cands, key=lambda c: abs(c - i))
        offsets.append(j - i)
    typical = sorted(offsets)[len(offsets) // 2] if offsets else 0

    assigned: list[int] = []
    for i, cands in enumerate(candidates):
        if not cands:
            continue
        expected = i + typical
        assigned.append(min(cands, key=lambda c: abs(c - expected)))
    return assigned


def _order_error(assigned: list[int]) -> float:
    """Share of consecutive matched lines whose truth index goes backwards."""
    if len(assigned) < 2:
        return 0.0
    inversions = sum(1 for a, b in zip(assigned, assigned[1:]) if b < a)
    return inversions / (len(assigned) - 1)


def score_output(output: list[str], truth: list[str]) -> dict:
    """Missed / duplicated / out-of-order line rates for one stitched transcript."""
    matched = _lcs_matched(output, truth)
    assigned = _assign_positions(output, truth)
    return {
        "truth_lines": len(truth),
        "output_lines": len(output),
        "matched_lines": matched,
        "miss_rate": round((len(truth) - matched) / max(1, len(truth)), 4),
        "dup_rate": round(max(0, len(output) - matched) / max(1, len(output)), 4),
        "order_error": round(_order_error(assigned), 4),
    }


def stitch_and_score(
    pages,
    truth: list[str],
    *,
    directions: list[int] | None = None,
    **stitcher_kwargs,
) -> tuple[dict, TranscriptStitcher]:
    """Run the stitcher over pre-built pages and return (metrics, stitcher)."""
    stitcher = TranscriptStitcher(**stitcher_kwargs)
    started = time.perf_counter()
    for index, page in enumerate(pages):
        direction = directions[index] if directions and index < len(directions) else 1
        stitcher.add_page(page, direction=direction)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    metrics = score_output(stitcher.text_lines, truth)
    metrics["elapsed_ms"] = round(elapsed_ms, 2)
    metrics["pages"] = stitcher.page_count
    metrics["breakpoints"] = len(stitcher.breakpoints)
    return metrics, stitcher

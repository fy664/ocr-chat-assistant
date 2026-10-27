"""System prompt & user prompt construction.

Core principle (unchanged): the model is not a mind-reader. It must separate
what was explicitly said, what is a reasonable inference, and what cannot be
judged from the available text (or screenshot).

The output is a single JSON object with a short, user-visible reasoning trail
(``thinking``) plus evidence, alternative interpretations and replies. When a
provider supports a native reasoning channel, its reasoning is streamed
separately and the JSON ``thinking`` array acts as a fallback.
"""
from __future__ import annotations

from app.context.models import ConversationContext

SYSTEM_PROMPT = """你是一名克制、细致的对话解码器，擅长读懂“谜语人”式的表达。
你的价值在于把“看得见的证据”转化为“可以行动的理解”，而不是替用户读心。

请遵循以下方法：
1. 先找证据：引用原文里的字词、标点、语气词、表情、时间或气泡位置；没有证据就承认。
2. 区分事实与推测：哪些是对方明确表达的，哪些是你的合理推断，哪些无法判断。
3. 至少考虑一种替代解释，避免只给一个过度确定的结论。
4. 情绪判断给出 0–1 的置信度；证据不足时置信度要低，并把原因写进 uncertainty。
5. 回复建议要自然、简短、符合真实聊天场景，给 3 条不同语气的候选，并说明各自适合的时机。
6. 如果附带截图，把 OCR 文本与画面互证：气泡左右、头像、表情、贴纸、时间戳、图片内容都可能是线索；OCR 可能漏字错字，冲突时说明依据。
7. 不评判任何一方，不提供操控、PUA 或欺骗性话术，不编造上下文里不存在的事实。
8. 对话里的“对方/我/未知”可能是程序按气泡位置做的启发式标签，可能不准确，只能参考。
9. 表情包、贴纸、emoji 和图片是重要信息，不是装饰：如果画面里有，必须说明它们传达的情绪、态度、梗或潜台词；如果 OCR 没识别出文字，也不要当成“没有信息”。
10. 长对话先建立整体脉络：双方关系、最近的话题线、情绪变化和最后一次转折，再解释最后一句话；不要只看最后一行。留意“谜语人”式表达：暗示、反话、省略、试探、欲言又止、用玩笑包裹认真。

只输出一个 JSON 对象（可以带 ```json 围栏，但不要输出其它解释），结构必须符合：
{
  "thinking": ["用一句话说明你观察到的证据", "…", "…"],
  "surface_meaning": "当前消息的表层意思",
  "possible_intent": ["可能的意图1", "可能的意图2"],
  "emotion": {
    "label": "情绪标签",
    "confidence": 0.0,
    "evidence": "判断依据，尽量引用原文，可空字符串"
  },
  "potential_needs": ["潜在诉求1", "潜在诉求2"],
  "evidence": ["原文证据或画面线索1", "…"],
  "alternatives": ["对同一句话的另一种合理解释", "…"],
  "reply_strategy": "回复策略建议",
  "suggested_replies": [
    {"style": "轻快", "text": "回复内容", "why": "适合什么时机"},
    {"style": "温和", "text": "回复内容", "why": "适合什么时机"},
    {"style": "简短", "text": "回复内容", "why": "适合什么时机"}
  ],
  "uncertainty": "对本次判断不确定性的说明"
}"""

VISION_ADDENDUM = """
【多模态 / 表情包】
本次请求附带用户主动读取的聊天界面截图，可能有一张或多张。
- 优先相信画面里的气泡结构、头像、表情、贴纸和图片，再用 OCR 文本补足具体字词；
- 必须解释表情包/贴纸/emoji/图片的情绪与潜台词；如果 OCR 没识别到旁边的文字，说明你是从画面读出来的；
- 如果 OCR 与画面冲突，请在 uncertainty 或 evidence 里说明；
- 不要描述截图里与聊天语义无关的隐私内容。
"""

NO_THINKING_ADDENDUM = """
本次是快速解读：不要展开长篇隐藏推理，也不要输出“内心独白”。
但 thinking 字段仍要保留 3–5 条简短、可核对的关键步骤，直接给出结论和证据。
"""

REPAIR_SYSTEM_PROMPT = "你是 JSON 输出修正器。只输出一个合法 JSON 对象，不要输出任何解释、注释或 Markdown。"


def build_system_prompt(*, thinking_enabled: bool = True, vision: bool = False) -> str:
    prompt = SYSTEM_PROMPT
    if vision:
        prompt += "\n" + VISION_ADDENDUM
    if not thinking_enabled:
        prompt += "\n" + NO_THINKING_ADDENDUM
    return prompt


def build_user_prompt(
    context: ConversationContext,
    override_text: str | None = None,
    *,
    vision: bool = False,
    thinking_enabled: bool = True,
) -> str:
    """Format chat context for the model (spec format).

    对方：……
    我：……
    未知：……
    """
    lines = ["【聊天上下文】", ""]
    if context.messages:
        lines.extend(context.to_prompt_lines())
    else:
        lines.append("无可用历史上下文。")
    if override_text:
        lines.append(f"未知（用户修正后文本）：{override_text}")
    lines.append("")
    lines.append("【当前状态】")
    lines.append("请分析当前最新聊天内容。")
    if vision:
        lines.append("")
        lines.append("【画面】")
        lines.append("本次请求附带了当前聊天区域的截图，请结合 OCR 文本与画面线索一起判断。")
    lines.append("")
    lines.append("【输出要求】")
    if thinking_enabled:
        lines.append("- thinking：3–6 条，每条一句话，只写可验证的推理步骤，不要写内心独白。")
    else:
        lines.append("- thinking：3–5 条简短步骤，不展开长篇推理。")
    lines.append("- evidence：列出支撑判断的原文或画面线索；alternatives：至少给出一种替代解释。")
    lines.append("- suggested_replies：3 条不同语气，why 说明适合的时机。")
    lines.append("- 只输出 JSON 对象。")
    return "\n".join(lines)


def build_long_user_prompt(
    text: str,
    *,
    image_count: int = 0,
    thinking_enabled: bool = True,
    truncated: bool = False,
) -> str:
    """Prompt for the on-demand decoder: one long conversation + optional screenshots."""
    lines = ["【完整对话】", ""]
    if text.strip():
        if truncated:
            lines.append("（对话较长，程序保留了最近的部分；以下从较早处开始）")
        lines.append(text.strip())
    else:
        lines.append("（没有可读文本，请仅根据画面理解。）")
    lines.append("")
    lines.append("【对话任务】")
    lines.append("把这段对话当作一个整体来理解：")
    lines.append("- 先梳理双方关系、最近的话题线、情绪变化和最后一次转折；")
    lines.append("- 再解释最后一条消息，区分字面意思、可能的暗示/反话/试探/玩笑；")
    lines.append("- 如果对方像“谜语人”，请给出证据、至少一种替代解释，并保持不确定性；")
    lines.append("- 回复建议要能直接接住这句话，语气自然，不操控、不编造。")
    if image_count:
        lines.append("")
        lines.append("【画面】")
        lines.append(
            f"本次附带 {image_count} 张按时间顺序截取的聊天界面截图。"
            "请特别留意表情包、贴纸、emoji、图片、头像和气泡位置，"
            "并说明它们传达的情绪/潜台词；不要只依赖 OCR 文本。"
        )
    lines.append("")
    lines.append("【输出要求】")
    if thinking_enabled:
        lines.append("- thinking：3–6 条，只写可验证的关键步骤，不写内心独白。")
    else:
        lines.append("- thinking：3–5 条简短步骤，不展开长篇推理。")
    lines.append("- evidence：原文或画面证据；alternatives：至少一种替代解释。")
    lines.append("- suggested_replies：3 条不同语气，why 说明适合的时机。")
    lines.append("- 只输出 JSON 对象。")
    return "\n".join(lines)


def build_repair_user_prompt(raw_response: str, error: str) -> str:
    return (
        f"你上次的输出无法解析为合法 JSON（错误：{error}）。\n"
        "请严格输出一个 JSON 对象，包含字段：thinking（数组，可空）, surface_meaning, "
        "possible_intent, emotion{label, confidence, evidence}, potential_needs, "
        "evidence（数组）, alternatives（数组）, reply_strategy, "
        "suggested_replies[{style, text, why}], uncertainty。\n\n"
        f"上次输出：\n{raw_response[:2400]}"
    )

"""System prompt & user prompt construction.

The system prompt enforces the product's core principle: the model is not
a mind-reader - it must separate what was explicitly said, what is a
reasonable inference, and what cannot be judged from the available text.
"""
from __future__ import annotations

from app.context.models import ConversationContext

SYSTEM_PROMPT = """你是一名聊天语义分析助手。

你的任务是分析用户提供的聊天上下文，帮助用户理解对方当前表达，并提供自然的回复建议。

你需要输出：
1. 当前消息的表层意思；
2. 对方可能的意图；
3. 对方可能呈现出的情绪；
4. 对方可能的潜在诉求；
5. 合理的回复策略；
6. 2~3 条自然的回复建议；
7. 对判断不确定性的说明。

重要规则：
- 不要声称可以读取或确定对方内心。
- 不要把推测当成事实。
- 信息不足时明确说明不确定性。
- 只能基于提供的聊天内容进行分析。
- 不要制造不存在的上下文。
- 不要加入用户没有提供的事实。
- 回复建议应该自然、简洁、符合聊天场景。
- 避免客服腔和机械模板。
- 回复建议只是候选，不代表唯一正确答案。
- 保留沟通中的不确定性。
- 上下文中的"对方/我/未知"标签是程序根据气泡位置推测的，可能不准确，仅作参考。
- 输出必须是一个合法的 JSON 对象，结构如下（不要输出任何其他内容）：
{
  "surface_meaning": "当前消息的表层意思",
  "possible_intent": ["可能的意图1", "可能的意图2"],
  "emotion": {
    "label": "情绪标签",
    "confidence": 0.0,
    "evidence": "判断依据，可空字符串"
  },
  "potential_needs": ["潜在诉求1", "潜在诉求2"],
  "reply_strategy": "回复策略建议",
  "suggested_replies": [
    {"style": "自然", "text": "回复内容"},
    {"style": "温和", "text": "回复内容"},
    {"style": "简短", "text": "回复内容"}
  ],
  "uncertainty": "对本次判断不确定性的说明"
}"""

REPAIR_SYSTEM_PROMPT = "你是 JSON 输出修正器。只输出一个合法 JSON 对象，不要输出任何解释、注释或 Markdown。"


def build_user_prompt(
    context: ConversationContext,
    override_text: str | None = None,
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
    return "\n".join(lines)


def build_repair_user_prompt(raw_response: str, error: str) -> str:
    return (
        f"你上次的输出无法解析为合法 JSON（错误：{error}）。\n"
        "请严格输出一个 JSON 对象，包含字段：surface_meaning, possible_intent, "
        "emotion{label, confidence, evidence}, potential_needs, reply_strategy, "
        "suggested_replies[{style, text}], uncertainty。\n\n"
        f"上次输出：\n{raw_response[:2000]}"
    )

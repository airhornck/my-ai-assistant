"""
创作结果后的反馈意图分类。
当会话存在「后续建议」时，判断用户回复是「明确采纳」「模糊评价」还是「未知」。

重要区分：「还好吧」等在不同上下文含义不同：
- 闲聊延续（如上轮仅为「你好」的 casual_reply）：表示「我还好」，应走闲聊回复
- 创作结果后（上轮有 generate/evaluate 输出）：表示对生成内容的模糊评价，需澄清引导
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# 模糊评价：用户对创作结果给出评价，但未明确表示是否执行后续建议
AMBIGUOUS_FEEDBACK_PHRASES = frozenset((
    "还不错", "还行", "一般", "可以吧", "还好", "还好吧", "嗯嗯", "哦", "哦哦", "嗯好",
))

# 明确采纳：用户明确表示要执行后续建议
ACCEPT_SUGGESTION_PHRASES = frozenset((
    "需要", "要", "要试试", "好的", "可以", "可以的", "试试", "采纳", "行", "好", "嗯",
))

# 寒暄用语：含「好」等字但非采纳意图，不当作采纳
GREETING_OR_CASUAL_PHRASES = frozenset((
    "你好", "你好啊", "嗨", "在吗", "在不在", "谢谢", "感谢",
))


@dataclass
class FeedbackIntentResult:
    """反馈意图分类结果"""

    accepted_suggestion: bool  # 是否明确采纳后续建议
    ambiguous_feedback: bool   # 是否为模糊评价（需生成澄清性问题）
    reason: str = ""


def classify_feedback_after_creation(
    user_msg: str,
    has_suggested_next_plan: bool,
    last_message_role: Optional[str] = None,
    previous_was_creation: bool = False,
) -> FeedbackIntentResult:
    """
    在「创作结果 + 存在后续建议」的上下文中，分类用户反馈意图。

    参数:
        user_msg: 用户当前输入（已 strip）
        has_suggested_next_plan: 会话是否存在可执行的后续建议
        last_message_role: 上一条消息的角色 ("user" | "assistant")，None 表示未知
        previous_was_creation: 上轮是否为创作输出（含 generate/evaluate），若仅为闲聊则 False。
            「还好吧」在闲聊延续时表示「我还好」，在创作结果后表示对内容的模糊评价。

    返回:
        FeedbackIntentResult: accepted_suggestion, ambiguous_feedback, reason
    """
    msg_clean = (user_msg or "").strip().strip("。！？,，、 ")
    if not msg_clean:
        return FeedbackIntentResult(accepted_suggestion=False, ambiguous_feedback=False, reason="empty")

    # 模糊评价：仅当上轮是创作输出时，才将「还好吧」等视为对创作内容的模糊评价；否则为闲聊延续
    if msg_clean in AMBIGUOUS_FEEDBACK_PHRASES:
        if has_suggested_next_plan and last_message_role == "assistant" and previous_was_creation:
            return FeedbackIntentResult(
                accepted_suggestion=False,
                ambiguous_feedback=True,
                reason="ambiguous_feedback",
            )
        return FeedbackIntentResult(accepted_suggestion=False, ambiguous_feedback=False, reason="ambiguous_not_in_context")

    # 明确采纳：排除寒暄用语（如「你好」「谢谢」含「好」但非采纳）
    if msg_clean in GREETING_OR_CASUAL_PHRASES:
        return FeedbackIntentResult(accepted_suggestion=False, ambiguous_feedback=False, reason="greeting_or_casual")
    msg_like_accept = (
        msg_clean in ACCEPT_SUGGESTION_PHRASES
        or (len(msg_clean) <= 6 and any(k in msg_clean for k in ("需", "要", "好", "可以", "试")))
    )
    if msg_like_accept:
        if has_suggested_next_plan:
            return FeedbackIntentResult(accepted_suggestion=True, ambiguous_feedback=False, reason="accept_from_session")
        if len(msg_clean) <= 15 and last_message_role == "assistant":
            return FeedbackIntentResult(accepted_suggestion=True, ambiguous_feedback=False, reason="accept_fallback")

    return FeedbackIntentResult(accepted_suggestion=False, ambiguous_feedback=False, reason="unknown")

"""
后续建议：根据专家经验给出如何进一步提升文章质量与关键指标（如浏览、转化）的建议；
若有可执行的下一步能力，再输出一句引导用户续聊的话术。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.api_config import get_model_config
from core.plugin_capabilities import get_all_followup_descriptions

logger = logging.getLogger(__name__)

FOLLOWUP_SYSTEM = """你是助手，在每轮对话后先给 1～3 条**自然、口语化**的专家建议，再视情况写一句引导，像在和朋友聊天。不要用「专家建议：」「引导句：」等标签。

**结构与语气**：
1. 先写 1～3 条具体建议（自然句）：例如补充关键维度、优化标题、多平台分发、明确平台与受众等，结合本轮内容用口语表达。
2. 再视是否到达终止点决定是否写一句引导：若还有自然下一步（如可生成、可分析），用一句自然话邀请，例如「如果你愿意，我可以帮你再生成一版更适合 B 站的文案。」「有具体方向或目标的话可以告诉我，我来帮你生成。」
3. 整段不要加任何标签，直接写给用户看。

**终止点**：当本轮已达成目标（已生成并评估、内容完整、用户无继续迭代意愿）时，只输出 1 条简短收尾，例如「本次内容已就绪，有新需求随时说。」**不要**再给可执行下一步，**不要**写 STEP。

**STEP 仅用于系统**：若需要系统执行下一步（generate 或 analyze），在回复的**最后单独另起一行**只写：STEP: generate 或 STEP: analyze。该行仅供系统识别，不会展示给用户，所以必须单独一行、不要和正文写在同一行。"""


def _parse_step_from_response(text: str) -> tuple[str, str]:
    """从 LLM 回复中解析 STEP: xxx，返回 (去掉 STEP 后的正文且不包含 STEP 字样, step_name)。"""
    if not text or not text.strip():
        return "", ""
    lines = text.strip().split("\n")
    step_name = ""
    rest_lines = []
    for line in lines:
        s = line.strip()
        if s.upper().startswith("STEP:"):
            step_name = s[5:].strip().lower()
            continue
        # 兜底：同一行末尾可能带「 STEP: generate」（不展示给用户）
        m = re.search(r"\s*STEP:\s*(generate|analyze)\s*$", s, re.IGNORECASE)
        if m:
            step_name = m.group(1).lower()
            s = s[: m.start()].strip()
        rest_lines.append(s)
    rest = "\n".join(rest_lines).strip()
    if step_name not in ("generate", "analyze"):
        step_name = "generate" if rest else ""
    return rest, step_name


async def get_follow_up_suggestion(
    user_input_str: str,
    intent: str,
    plan: list[dict],
    step_outputs: list[dict],
    content_preview: str,
) -> tuple[str, str]:
    """
    根据本轮执行情况与插件能力，生成一句后续建议；若意图已满足则返回 ("", "")。
    若有建议，则同时返回 (引导话术, 建议执行的步骤名 generate|analyze)，供用户采纳后直接执行。
    """
    try:
        data = {}
        if isinstance(user_input_str, str) and user_input_str.strip():
            try:
                data = json.loads(user_input_str)
            except (TypeError, json.JSONDecodeError):
                pass
        steps_done = [s.get("step", "") for s in (plan or []) if s.get("step")]
        capabilities = get_all_followup_descriptions()
        cap_text = "\n".join(f"- {name}: {desc}" for name, desc in capabilities)

        user_prompt = f"""【用户意图】{intent or "未指定"}
【本轮已执行步骤】{", ".join(steps_done) or "无"}
【当前输出摘要】{content_preview[:400] if content_preview else "无"}

【系统还能提供的能力（分析脑与生成脑插件）】
{cap_text}

请根据上面信息，先给 1 条自然口语化的建议，来引导用户是否回答意图“需要”等的答案，不再写引导句；不要加「专家建议：」「引导句：」等标签。若本轮已达成目标就简短收尾；若还有自然下一步，用自然话邀请（如「如果你愿意……，我可以帮你……」），并在**最后单独另起一行**只写 STEP: generate 或 STEP: analyze（该行不会展示给用户）。"""
        messages = [
            SystemMessage(content=FOLLOWUP_SYSTEM),
            HumanMessage(content=user_prompt),
        ]
        cfg = get_model_config("thinking_narrative")
        client = ChatOpenAI(
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            temperature=cfg.get("temperature", 0.3),
            max_tokens=cfg.get("max_tokens", 512),
        )
        response = await client.ainvoke(messages)
        text = (response.content or "").strip() if hasattr(response, "content") else str(response).strip()
        if not text or len(text) < 10:
            return "", ""
        suggestion_text, step_name = _parse_step_from_response(text)
        if not suggestion_text or len(suggestion_text) < 5:
            return "", ""
        # 无 STEP 表示终止点，不设置 suggested_next_plan，避免永无止境的建议
        return suggestion_text, step_name
    except Exception as e:
        logger.warning("后续建议生成失败: %s", e, exc_info=True)
        return "", ""

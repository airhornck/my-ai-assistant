"""
文本/图文爆款结构拆解插件：分析脑实时插件。
参考 Veogo AI：标题套路、开头 hooks、分点阐述、话术设计、互动引导。
依赖：ai_service（LLM 提炼）；无 video_decomposition。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

FALLBACK = """【文本/图文爆款结构拆解】
标题：数字/悬念/利益点
开头：前3句吸睛，抛出钩子
分点：3-5 个要点，每点 1-2 句
话术：口语化、有代入感
互动：结尾引导点赞/评论/收藏
（LLM 未配置时使用兜底）"""


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """注册文本/图文爆款结构拆解插件。"""
    ai_service = config.get("ai_service")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        existing = context.get("analysis") or {}
        if not isinstance(existing, dict):
            existing = {}
        pi = context.get("plugin_input") or {}
        script = pi.get("script", "") or pi.get("raw_text", "")
        platform = pi.get("platform", "") or "default"
        pref = context.get("preference_context", "")

        if not ai_service:
            return {"analysis": {**existing, "text_viral_structure": FALLBACK}}

        prompt = f"""请对以下文本/图文内容进行爆款结构拆解。

【内容】
{script[:2000] if script else '（无内容，请基于通用爆款结构输出）'}

【平台】{platform}

请输出结构化的拆解，包含：
1. 标题套路（如 数字型、悬念型、利益点）
2. 开头 hooks（前 3 句的吸睛手法）
3. 分点阐述方式（要点数量、每点篇幅）
4. 话术设计（语气、代入感）
5. 结尾互动引导

用简洁的 bullet 或分点形式，控制在 300 字以内。"""
        try:
            llm = ai_service._llm
            raw = await llm.invoke(
                [SystemMessage(content="你是爆款内容结构分析专家。"), HumanMessage(content=prompt)],
                task_type="analysis",
                complexity="medium",
            )
            report = (raw or "").strip() or FALLBACK
            return {"analysis": {**existing, "text_viral_structure": report}}
        except Exception as e:
            logger.warning("文本爆款结构拆解失败: %s", e)
            return {"analysis": {**existing, "text_viral_structure": FALLBACK}}

    plugin_center.register_plugin(
        "text_viral_structure",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

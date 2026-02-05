"""
活动策划上下文拼装插件：分析脑实时插件，拼装逻辑在插件中心内完成。
get_output 时调用同脑内 methodology、case_library、knowledge_base 插件的 get_output，再拼成 campaign_context。
规划脑只登记本插件名（campaign_context），不登记子插件。
"""
from __future__ import annotations

import logging
from typing import Any

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """向分析脑插件中心注册拼装插件。必须在 methodology、case_library、knowledge_base 之后注册。"""
    center = plugin_center

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """调用同脑内 methodology、case_library、knowledge_base 的 get_output，拼装为 campaign_context。"""
        existing_analysis = context.get("analysis") or {}
        if not isinstance(existing_analysis, dict):
            existing_analysis = {}
        parts = []
        for sub_name in ("methodology", "case_library", "knowledge_base"):
            if not center.has_plugin(sub_name):
                continue
            try:
                out = await center.get_output(sub_name, context)
                if out and isinstance(out, dict) and "analysis" in out:
                    val = out["analysis"].get(sub_name)
                    if val and isinstance(val, str) and val.strip():
                        if sub_name == "methodology":
                            parts.append("【营销方法论】\n\n" + val.strip())
                        elif sub_name == "case_library":
                            parts.append("【参考案例】\n\n" + val.strip())
                        else:
                            parts.append("【行业知识】\n\n" + val.strip())
            except Exception as e:
                logger.debug("campaign_context 子插件 %s 失败: %s", sub_name, e)
        campaign_context = "\n\n".join(parts).strip() if parts else "（暂无方法论/案例/知识库，请等待定时刷新或配置）"
        return {"analysis": {**existing_analysis, "campaign_context": campaign_context}}

    plugin_center.register_plugin(
        "campaign_context",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

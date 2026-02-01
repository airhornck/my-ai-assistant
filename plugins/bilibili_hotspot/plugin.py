"""
B站热点榜单插件：分析脑的定时插件。
声明类型为 定时插件，刷新逻辑由脑级插件中心管理。
"""
from __future__ import annotations

import logging
from typing import Any

from cache.smart_cache import BILIBILI_HOTSPOT_CACHE_KEY
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_SCHEDULED

logger = logging.getLogger(__name__)

FALLBACK_REPORT = """【B站热点参考】
结构：标题抓眼球、开头 hooks、分点阐述、结尾互动求三连
风格：年轻化、有梗、弹幕文化、awsl/yyds/绝绝子等流行语、轻松接地气
热点 IP 借鉴：结合品牌调性做差异化表达，保持互动感"""


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """
    向分析脑插件中心注册 B站热点榜单插件。
    插件类型：定时插件。刷新由插件中心调度。
    """
    cache = config.get("cache")
    ai_service = config.get("ai_service")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """获取插件输出：读缓存，未命中则返回兜底。"""
        existing_analysis = context.get("analysis") or {}
        hotspot_text = FALLBACK_REPORT
        if cache is not None:
            try:
                payload = await cache.get(BILIBILI_HOTSPOT_CACHE_KEY)
                if isinstance(payload, dict) and payload.get("report"):
                    hotspot_text = payload["report"].strip()
            except Exception as e:
                logger.debug("B站热点缓存读取失败: %s，使用兜底", e)
        if not isinstance(existing_analysis, dict):
            existing_analysis = {}
        return {"analysis": {**existing_analysis, "bilibili_hotspot": hotspot_text}}

    async def refresh() -> None:
        """定时刷新：搜索 + LLM 提炼 → 写入缓存。"""
        from services.bilibili_hotspot_refresh import refresh_bilibili_hotspot_report
        await refresh_bilibili_hotspot_report(
            cache=cache,
            ai_service=ai_service,
        )

    plugin_center.register_plugin(
        "bilibili_hotspot",
        PLUGIN_TYPE_SCHEDULED,
        get_output=get_output,
        refresh_func=refresh,
        schedule_config={"interval_hours": 6},
    )

"""
小红书热点插件：分析脑的定时插件。
"""
from __future__ import annotations
import logging
from typing import Any
from cache.smart_cache import XIAOHONGSHU_HOTSPOT_CACHE_KEY
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_SCHEDULED

logger = logging.getLogger(__name__)

FALLBACK_REPORT = "【小红书热点参考】\n话题：极简生活、OOTD\n风格：高颜值、干货满满"

def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    cache = config.get("cache")
    ai_service = config.get("ai_service")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        existing_analysis = context.get("analysis") or {}
        hotspot_text = FALLBACK_REPORT
        if cache:
            try:
                payload = await cache.get(XIAOHONGSHU_HOTSPOT_CACHE_KEY)
                if isinstance(payload, dict) and payload.get("report"):
                    hotspot_text = payload["report"].strip()
            except Exception as e:
                logger.debug("小红书缓存读取失败: %s", e)
        return {"analysis": {**existing_analysis, "xiaohongshu_hotspot": hotspot_text}}

    async def refresh() -> None:
        from services.xiaohongshu_hotspot_refresh import refresh_xiaohongshu_hotspot_report
        await refresh_xiaohongshu_hotspot_report(cache=cache, ai_service=ai_service)

    plugin_center.register_plugin(
        "xiaohongshu_hotspot",
        PLUGIN_TYPE_SCHEDULED,
        get_output=get_output,
        refresh_func=refresh,
        schedule_config={"interval_hours": 6},
    )

"""
A站热点插件：分析脑的定时插件。
"""
from __future__ import annotations
import logging
from typing import Any
from cache.smart_cache import ACFUN_HOTSPOT_CACHE_KEY
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_SCHEDULED

logger = logging.getLogger(__name__)

FALLBACK_REPORT = "【AcFun热点参考】\n硬核科普、游戏速通\nTD、AC娘表情包"

def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    cache = config.get("cache")
    ai_service = config.get("ai_service")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        existing_analysis = context.get("analysis") or {}
        hotspot_text = FALLBACK_REPORT
        if cache:
            try:
                payload = await cache.get(ACFUN_HOTSPOT_CACHE_KEY)
                if isinstance(payload, dict) and payload.get("report"):
                    hotspot_text = payload["report"].strip()
            except Exception as e:
                logger.debug("A站缓存读取失败: %s", e)
        return {"analysis": {**existing_analysis, "acfun_hotspot": hotspot_text}}

    async def refresh() -> None:
        from services.acfun_hotspot_refresh import refresh_acfun_hotspot_report
        await refresh_acfun_hotspot_report(cache=cache, ai_service=ai_service)

    plugin_center.register_plugin(
        "acfun_hotspot",
        PLUGIN_TYPE_SCHEDULED,
        get_output=get_output,
        refresh_func=refresh,
        schedule_config={"interval_hours": 6},
    )

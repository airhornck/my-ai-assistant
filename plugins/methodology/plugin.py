"""
营销方法论插件：分析脑定时插件。
refresh 将方法论文档拼成报告写入缓存，get_output 只读缓存；支持灵活配置 cache_key、刷新频率、TTL。
"""
from __future__ import annotations

import logging
from typing import Any

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_SCHEDULED

logger = logging.getLogger(__name__)

# 默认配置（可被 config 覆盖）
DEFAULT_CACHE_KEY = "plugin:analysis:methodology:report"
DEFAULT_REFRESH_INTERVAL_HOURS = 6
DEFAULT_TTL_SECONDS = 21600  # 6 小时
DEFAULT_MAX_DOCS = 10
DEFAULT_MAX_CONTENT_LENGTH = 800  # 每篇截断长度


def _get_config(config: dict[str, Any]) -> dict[str, Any]:
    """从插件中心 config 读取配置，未提供则用默认值。"""
    plugin_cfg = config.get("methodology_plugin") or {}
    return {
        "cache_key": plugin_cfg.get("cache_key") or DEFAULT_CACHE_KEY,
        "refresh_interval_hours": plugin_cfg.get("refresh_interval_hours", DEFAULT_REFRESH_INTERVAL_HOURS),
        "ttl_seconds": plugin_cfg.get("ttl_seconds", DEFAULT_TTL_SECONDS),
        "max_docs": plugin_cfg.get("max_docs", DEFAULT_MAX_DOCS),
        "max_content_length": plugin_cfg.get("max_content_length", DEFAULT_MAX_CONTENT_LENGTH),
    }


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """向分析脑插件中心注册营销方法论插件。类型：定时插件。"""
    cache = config.get("cache")
    methodology_service = config.get("methodology_service")
    cfg = _get_config(config)

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """只读缓存；未命中返回兜底文案，不在此刻调 MethodologyService。"""
        existing_analysis = context.get("analysis") or {}
        if not isinstance(existing_analysis, dict):
            existing_analysis = {}
        text = "（暂无方法论报告，请等待定时刷新或检查配置）"
        if cache is not None:
            try:
                payload = await cache.get(cfg["cache_key"])
                if isinstance(payload, str):
                    text = payload
                elif isinstance(payload, dict) and payload.get("report"):
                    text = payload["report"].strip()
            except Exception as e:
                logger.debug("methodology 缓存读取失败: %s", e)
        return {"analysis": {**existing_analysis, "methodology": text}}

    async def refresh() -> None:
        """定时刷新：拉取方法论文档，拼成报告写入缓存。"""
        if methodology_service is None:
            logger.warning("methodology 插件未注入 methodology_service，跳过刷新")
            return
        if cache is None:
            logger.warning("methodology 插件未注入 cache，跳过刷新")
            return
        try:
            docs = methodology_service.list_docs()
            parts = []
            for d in docs[: cfg["max_docs"]]:
                path = d.get("path") or (d.get("name") or "") + ".md"
                content = methodology_service.get_content(path)
                if content:
                    parts.append(content[: cfg["max_content_length"]])
            report = "\n\n".join(parts).strip() if parts else "（暂无方法论文档）"
            payload = {"report": report}
            await cache.set(cfg["cache_key"], payload, ttl=cfg["ttl_seconds"])
            logger.info("methodology 插件已刷新，cache_key=%s，片段数=%d", cfg["cache_key"], len(parts))
        except Exception as e:
            logger.warning("methodology 插件刷新失败: %s", e, exc_info=True)

    plugin_center.register_plugin(
        "methodology",
        PLUGIN_TYPE_SCHEDULED,
        get_output=get_output,
        refresh_func=refresh,
        schedule_config={"interval_hours": cfg["refresh_interval_hours"]},
    )

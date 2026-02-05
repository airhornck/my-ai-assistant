"""
案例库插件：分析脑定时插件。
refresh 将案例列表/内容拼成报告写入缓存，get_output 只读缓存；支持灵活配置 cache_key、刷新频率、TTL、条数。
"""
from __future__ import annotations

import logging
from typing import Any

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_SCHEDULED

logger = logging.getLogger(__name__)

# 默认配置（可被 config 覆盖）
DEFAULT_CACHE_KEY = "plugin:analysis:case_library:report"
DEFAULT_REFRESH_INTERVAL_HOURS = 6
DEFAULT_TTL_SECONDS = 21600  # 6 小时
DEFAULT_PAGE_SIZE = 5
DEFAULT_MAX_CONTENT_LENGTH = 1200  # 每条案例内容截断长度


def _get_config(config: dict[str, Any]) -> dict[str, Any]:
    """从插件中心 config 读取配置，未提供则用默认值。"""
    plugin_cfg = config.get("case_library_plugin") or {}
    return {
        "cache_key": plugin_cfg.get("cache_key") or DEFAULT_CACHE_KEY,
        "refresh_interval_hours": plugin_cfg.get("refresh_interval_hours", DEFAULT_REFRESH_INTERVAL_HOURS),
        "ttl_seconds": plugin_cfg.get("ttl_seconds", DEFAULT_TTL_SECONDS),
        "page_size": plugin_cfg.get("page_size", DEFAULT_PAGE_SIZE),
        "max_content_length": plugin_cfg.get("max_content_length", DEFAULT_MAX_CONTENT_LENGTH),
    }


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """向分析脑插件中心注册案例库插件。类型：定时插件。"""
    cache = config.get("cache")
    case_service = config.get("case_service")
    cfg = _get_config(config)

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """只读缓存；未命中返回兜底文案，不在此刻调 CaseTemplateService。"""
        existing_analysis = context.get("analysis") or {}
        if not isinstance(existing_analysis, dict):
            existing_analysis = {}
        text = "（暂无案例库报告，请等待定时刷新或检查配置）"
        if cache is not None:
            try:
                payload = await cache.get(cfg["cache_key"])
                if isinstance(payload, str):
                    text = payload
                elif isinstance(payload, dict) and payload.get("report"):
                    text = payload["report"].strip()
            except Exception as e:
                logger.debug("case_library 缓存读取失败: %s", e)
        return {"analysis": {**existing_analysis, "case_library": text}}

    async def refresh() -> None:
        """定时刷新：拉取案例列表（按分排序、含内容），拼成报告写入缓存。"""
        if case_service is None:
            logger.warning("case_library 插件未注入 case_service，跳过刷新")
            return
        if cache is None:
            logger.warning("case_library 插件未注入 cache，跳过刷新")
            return
        try:
            result = await case_service.list_cases(
                order_by_score=True,
                page=1,
                page_size=cfg["page_size"],
                include_content=True,
            )
            items = result.get("items") or []
            parts = []
            for x in items:
                title = x.get("title", "")
                content = x.get("content") or x.get("summary") or ""
                parts.append(
                    f"【案例】{title}\n{(content[: cfg['max_content_length']]) if content else ''}"
                )
            report = "\n\n".join(parts).strip() if parts else "（暂无案例）"
            payload = {"report": report}
            await cache.set(cfg["cache_key"], payload, ttl=cfg["ttl_seconds"])
            logger.info("case_library 插件已刷新，cache_key=%s，条数=%d", cfg["cache_key"], len(parts))
        except Exception as e:
            logger.warning("case_library 插件刷新失败: %s", e, exc_info=True)

    plugin_center.register_plugin(
        "case_library",
        PLUGIN_TYPE_SCHEDULED,
        get_output=get_output,
        refresh_func=refresh,
        schedule_config={"interval_hours": cfg["refresh_interval_hours"]},
    )

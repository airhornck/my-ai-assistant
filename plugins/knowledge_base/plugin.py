"""
知识库插件：分析脑实时插件 + 强缓存。
get_output 先按 query 查缓存，命中则直接返回；未命中再调用 KnowledgePort.retrieve 并回写缓存。
支持灵活配置 cache_key_prefix、ttl_seconds、top_k。
"""
from __future__ import annotations

import logging
from typing import Any

from cache.smart_cache import build_fingerprint_key
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

# 默认配置（可被 config 覆盖）
DEFAULT_CACHE_KEY_PREFIX = "plugin:analysis:kb:"
DEFAULT_TTL_SECONDS = 3600  # 1 小时
DEFAULT_TOP_K = 4


def _get_config(config: dict[str, Any]) -> dict[str, Any]:
    """从插件中心 config 读取配置，未提供则用默认值。"""
    plugin_cfg = config.get("knowledge_base_plugin") or {}
    return {
        "cache_key_prefix": plugin_cfg.get("cache_key_prefix") or DEFAULT_CACHE_KEY_PREFIX,
        "ttl_seconds": plugin_cfg.get("ttl_seconds", DEFAULT_TTL_SECONDS),
        "top_k": plugin_cfg.get("top_k", DEFAULT_TOP_K),
    }


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """向分析脑插件中心注册知识库插件。类型：实时 + 缓存。"""
    cache = config.get("cache")
    knowledge_port = config.get("knowledge_port")
    cfg = _get_config(config)

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """先查缓存（按 query 的 key），命中则返回；未命中再 retrieve 并回写缓存。"""
        existing_analysis = context.get("analysis") or {}
        if not isinstance(existing_analysis, dict):
            existing_analysis = {}
        request = context.get("request")
        brand = getattr(request, "brand_name", "") or "" if request else ""
        product = getattr(request, "product_desc", "") or "" if request else ""
        topic = getattr(request, "topic", "") or "" if request else ""
        query = f"{brand} {product} {topic}".strip() or "营销策略"
        key = build_fingerprint_key(cfg["cache_key_prefix"], {"query": query})

        text = ""
        if cache is not None:
            try:
                payload = await cache.get(key)
                if isinstance(payload, dict) and "passages" in payload:
                    text = "\n\n".join(payload["passages"]) if payload["passages"] else ""
                elif isinstance(payload, str):
                    text = payload
            except Exception as e:
                logger.debug("knowledge_base 缓存读取失败: %s", e)

        if not text and knowledge_port is not None:
            try:
                passages = await knowledge_port.retrieve(query, top_k=cfg["top_k"])
                text = "\n\n".join(passages) if passages else ""
                if cache is not None and text:
                    await cache.set(key, {"passages": passages}, ttl=cfg["ttl_seconds"])
            except Exception as e:
                logger.warning("knowledge_base 检索失败: %s", e)

        if not text:
            text = "（暂无相关知识库内容）"
        return {"analysis": {**existing_analysis, "knowledge_base": text}}

    plugin_center.register_plugin(
        "knowledge_base",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

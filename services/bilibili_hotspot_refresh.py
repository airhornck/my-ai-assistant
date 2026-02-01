"""
B站热点榜单定时任务：检索 B站热门内容，提炼结构与风格，写入 Redis 供策略调用时只读。
报告聚焦：帮助用户分析如何打造热点 IP、内容结构与风格等，供生成脑借鉴。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from cache.smart_cache import (
    BILIBILI_HOTSPOT_CACHE_KEY,
    TTL_BILIBILI_HOTSPOT,
    SmartCache,
)
from config.search_config import get_search_config
from core.search import WebSearcher
from services.ai_service import SimpleAIService

logger = logging.getLogger(__name__)

BILIBILI_HOTSPOT_SYSTEM = """你是 B站内容分析专家。根据给定的 B站热门/热搜相关信息，提炼出：
1. **典型文章结构**：标题套路、开头 hooks、正文分点方式、结尾互动形式
2. **创作风格**：语言特点（年轻化、有梗、弹幕文化）、常用表达、情感基调
3. **可借鉴要点**：适合推广类内容、热点 IP 打造借鉴的具体写法

输出要求：用清晰的 bullet 或分点形式，便于后续生成文案时直接参考。控制在 400 字以内。"""


async def refresh_bilibili_hotspot_report(
    cache: SmartCache | None = None,
    ai_service: SimpleAIService | None = None,
    web_searcher: WebSearcher | None = None,
) -> str:
    """
    执行 B站热点榜单刷新：搜索 + LLM 提炼 → 写入 Redis。
    供定时任务或启动时调用。

    Returns:
        报告文本（已写入缓存）
    """
    cache = cache or SmartCache()
    ai_svc = ai_service or SimpleAIService()
    if web_searcher is None:
        cfg = get_search_config()
        web_searcher = WebSearcher(
            api_key=cfg.get("baidu_api_key"),
            provider=cfg.get("provider", "mock"),
            base_url=cfg.get("baidu_base_url"),
            top_k=cfg.get("baidu_top_k", 20),
        )

    search_query = "B站 bilibili 热门 热搜 热门视频 2025 爆款 创作风格 热点IP"
    try:
        results = await web_searcher.search(search_query, num_results=5)
        search_ctx = web_searcher.format_results_as_context(results)
    except Exception as e:
        logger.warning("B站热点刷新搜索失败: %s，使用兜底", e)
        search_ctx = "（搜索暂不可用，请基于你对 B站热门内容的了解作答）"

    user_prompt = f"""【B站相关信息】
{search_ctx[:2000]}

请提炼 B站热点内容的典型结构与创作风格，供后续生成 B站推广文案、打造热点 IP 时参考。"""
    messages = [
        SystemMessage(content=BILIBILI_HOTSPOT_SYSTEM),
        HumanMessage(content=user_prompt),
    ]
    try:
        llm = ai_svc._llm
        raw = await llm.invoke(messages, task_type="analysis", complexity="medium")
        hotspot_text = (raw or "").strip()
    except Exception as e:
        logger.warning("B站热点刷新 LLM 失败: %s", e)
        hotspot_text = (
            "【B站热点参考】\n"
            "结构：标题抓眼球、开头 hooks、分点阐述、结尾互动求三连\n"
            "风格：年轻化、有梗、弹幕文化、awsl/yyds/绝绝子等流行语、轻松接地气\n"
            "热点 IP 借鉴：结合品牌调性做差异化表达，保持互动感"
        )

    payload: dict[str, Any] = {"report": hotspot_text}
    await cache.set(BILIBILI_HOTSPOT_CACHE_KEY, payload, ttl=TTL_BILIBILI_HOTSPOT)
    logger.info("B站热点榜单报告已刷新并写入缓存")
    return hotspot_text

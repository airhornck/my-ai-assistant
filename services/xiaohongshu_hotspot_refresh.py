"""
小红书热点榜单定时任务：
1. 搜索小红书热搜、流行趋势。
2. LLM 提炼视觉/文案风格。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from cache.smart_cache import (
    XIAOHONGSHU_HOTSPOT_CACHE_KEY,
    TTL_XIAOHONGSHU_HOTSPOT,
    SmartCache,
)
from config.search_config import get_search_config
from core.search import WebSearcher
from services.ai_service import SimpleAIService

logger = logging.getLogger(__name__)

XHS_HOTSPOT_SYSTEM = """你是小红书内容营销专家。根据给定的热门/趋势信息，提炼出：
1. **热门话题**：当下最火的生活方式、穿搭、美妆、探店等关键词。
2. **封面美学**：首图构图、字体风格、色彩搭配建议。
3. **爆款标题**：关键词堆砌、情绪价值、实用干货（如“保姆级教程”、“绝绝子”）。
4. **正文结构**：Emoji排版、分段逻辑、标签（Hashtags）使用。

输出要求：清晰分点，侧重视觉与文案风格。控制在 500 字以内。"""

async def refresh_xiaohongshu_hotspot_report(
    cache: SmartCache | None = None,
    ai_service: SimpleAIService | None = None,
    web_searcher: WebSearcher | None = None,
) -> str:
    """
    刷新小红书热点报告。
    """
    cache = cache or SmartCache()
    ai_svc = ai_service or SimpleAIService()
    
    source_type = "Search"
    if web_searcher is None:
        cfg = get_search_config()
        web_searcher = WebSearcher(
            api_key=cfg.get("baidu_api_key"),
            provider=cfg.get("provider", "mock"),
            base_url=cfg.get("baidu_base_url"),
            top_k=cfg.get("baidu_top_k", 20),
        )
    
    search_query = "小红书热搜 流行趋势 2025 爆款笔记 封面风格"
    try:
        results = await web_searcher.search(search_query, num_results=5)
        context_text = web_searcher.format_results_as_context(results)
    except Exception as e:
        logger.warning("小红书热点刷新搜索失败: %s，使用兜底", e)
        context_text = "（搜索暂不可用，请基于你对小红书热门内容的了解作答）"

    user_prompt = f"""【小红书相关信息（来源：{source_type}）】
{context_text[:3000]}

请提炼小红书热点趋势与创作技巧，供后续生成种草笔记时参考。"""

    messages = [
        SystemMessage(content=XHS_HOTSPOT_SYSTEM),
        HumanMessage(content=user_prompt),
    ]
    
    try:
        llm = ai_svc._llm
        raw = await llm.invoke(messages, task_type="analysis", complexity="medium")
        hotspot_text = (raw or "").strip()
    except Exception as e:
        logger.warning("小红书热点刷新 LLM 失败: %s", e)
        hotspot_text = (
            "【小红书热点参考】\n"
            "话题：极简生活、OOTD、沉浸式\n"
            "封面：高颜值、对比强烈、大字标题\n"
            "文案：真诚分享、Emoji丰富、干货满满"
        )

    payload: dict[str, Any] = {"report": hotspot_text, "source": source_type}
    await cache.set(XIAOHONGSHU_HOTSPOT_CACHE_KEY, payload, ttl=TTL_XIAOHONGSHU_HOTSPOT)
    logger.info(f"小红书热点榜单报告已刷新并写入缓存")
    return hotspot_text

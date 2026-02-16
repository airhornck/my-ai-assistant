"""
抖音热点榜单定时任务：
1. 尝试搜索抖音热点（因 API 严格限制）。
2. LLM 提炼分析。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from cache.smart_cache import (
    DOUYIN_HOTSPOT_CACHE_KEY,
    TTL_DOUYIN_HOTSPOT,
    SmartCache,
)
from config.search_config import get_search_config
from core.search import WebSearcher
from services.ai_service import SimpleAIService

logger = logging.getLogger(__name__)

DOUYIN_HOTSPOT_SYSTEM = """你是抖音短视频内容分析专家。根据给定的热门/热搜信息，提炼出：
1. **热门趋势**：当前抖音最火的 BGM、挑战赛、特效、话题。
2. **黄金3秒**：热门视频的开头吸睛技巧（视觉/听觉）。
3. **爆款公式**：脚本结构（如：反转、共情、干货输出）。
4. **互动引导**：如何引导点赞、评论、转发。

输出要求：清晰分点，便于创作参考。控制在 500 字以内。"""

async def refresh_douyin_hotspot_report(
    cache: SmartCache | None = None,
    ai_service: SimpleAIService | None = None,
    web_searcher: WebSearcher | None = None,
) -> str:
    """
    刷新抖音热点报告。
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
    
    search_query = "抖音热搜榜 热门话题 2025 爆款BGM 挑战赛"
    try:
        results = await web_searcher.search(search_query, num_results=5)
        context_text = web_searcher.format_results_as_context(results)
    except Exception as e:
        logger.warning("抖音热点刷新搜索失败: %s，使用兜底", e)
        context_text = "（搜索暂不可用，请基于你对抖音热门内容的了解作答）"

    user_prompt = f"""【抖音相关信息（来源：{source_type}）】
{context_text[:3000]}

请提炼抖音热点内容的趋势与创作技巧，供后续生成抖音短视频脚本时参考。"""

    messages = [
        SystemMessage(content=DOUYIN_HOTSPOT_SYSTEM),
        HumanMessage(content=user_prompt),
    ]
    
    try:
        llm = ai_svc._llm
        raw = await llm.invoke(messages, task_type="analysis", complexity="medium")
        hotspot_text = (raw or "").strip()
    except Exception as e:
        logger.warning("抖音热点刷新 LLM 失败: %s", e)
        hotspot_text = (
            "【抖音热点参考】\n"
            "趋势：快节奏、强反转、热门BGM卡点\n"
            "黄金3秒：提问、夸张表情、冲突画面\n"
            "互动：评论区埋梗、引导@好友"
        )

    payload: dict[str, Any] = {"report": hotspot_text, "source": source_type}
    await cache.set(DOUYIN_HOTSPOT_CACHE_KEY, payload, ttl=TTL_DOUYIN_HOTSPOT)
    logger.info(f"抖音热点榜单报告已刷新并写入缓存")
    return hotspot_text

"""
A站（AcFun）热点榜单定时任务：
1. 尝试 API 抓取（如果可行）。
2. 回退搜索。
3. LLM 提炼二次元/硬核御宅文化。
"""
from __future__ import annotations

import logging
import httpx
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from cache.smart_cache import (
    ACFUN_HOTSPOT_CACHE_KEY,
    TTL_ACFUN_HOTSPOT,
    SmartCache,
)
from config.search_config import get_search_config
from core.search import WebSearcher
from services.ai_service import SimpleAIService

logger = logging.getLogger(__name__)

ACFUN_HOTSPOT_SYSTEM = """你是 AcFun（A站）内容分析专家。根据给定的热门信息，提炼出：
1. **硬核趋势**：当前A站热门的硬核科普、游戏速通、买买买、手工制作等内容。
2. **社区梗**：当前的流行梗、评论区氛围（TD、AC娘等）。
3. **文章/视频结构**：标题党程度、封面风格、内容深度要求。

输出要求：清晰分点，侧重硬核与社区氛围。控制在 500 字以内。"""

async def _fetch_acfun_hot_list(limit: int = 15) -> str:
    """
    尝试从 A站 API 获取排行榜。
    Endpoint: https://www.acfun.cn/rest/pc-direct/rank/channel?channelId=&subChannelId=&rankLimit=30&rankPeriod=DAY
    """
    url = "https://www.acfun.cn/rest/pc-direct/rank/channel?channelId=&subChannelId=&rankLimit=30&rankPeriod=DAY"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.acfun.cn/rank/list",
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return ""
            
            data = resp.json()
            items = data.get("rankList", [])
            if not items:
                return ""
            
            lines = ["【AcFun 当前热门榜单】"]
            for i, item in enumerate(items[:limit], 1):
                title = item.get("contentTitle", "无标题")
                user = item.get("userName", "未知UP")
                views = item.get("viewCount", 0)
                desc = item.get("contentDesc", "").replace("\n", " ")[:100]
                
                lines.append(f"{i}. 标题：{title}")
                lines.append(f"   UP主：{user} | 播放：{views}")
                lines.append(f"   简介：{desc}...")
                lines.append("")
            
            return "\n".join(lines)
            
    except Exception as e:
        logger.warning(f"AcFun API 抓取异常: {e}")
        return ""

async def refresh_acfun_hotspot_report(
    cache: SmartCache | None = None,
    ai_service: SimpleAIService | None = None,
    web_searcher: WebSearcher | None = None,
) -> str:
    """
    刷新 A站热点报告。
    """
    cache = cache or SmartCache()
    ai_svc = ai_service or SimpleAIService()
    
    # 1. API
    context_text = await _fetch_acfun_hot_list()
    source_type = "API"
    
    # 2. Search Fallback
    if not context_text:
        source_type = "Search"
        if web_searcher is None:
            cfg = get_search_config()
            web_searcher = WebSearcher(
                api_key=cfg.get("baidu_api_key"),
                provider=cfg.get("provider", "mock"),
                base_url=cfg.get("baidu_base_url"),
                top_k=cfg.get("baidu_top_k", 20),
            )
        
        search_query = "AcFun A站 排行榜 热门视频 2025"
        try:
            results = await web_searcher.search(search_query, num_results=5)
            context_text = web_searcher.format_results_as_context(results)
        except Exception as e:
            logger.warning("AcFun 热点刷新搜索失败: %s，使用兜底", e)
            context_text = "（搜索暂不可用，请基于你对 A站内容的了解作答）"

    user_prompt = f"""【AcFun 相关信息（来源：{source_type}）】
{context_text[:3000]}

请提炼 A站热点趋势与创作技巧，供后续生成 A站内容时参考。"""

    messages = [
        SystemMessage(content=ACFUN_HOTSPOT_SYSTEM),
        HumanMessage(content=user_prompt),
    ]
    
    try:
        llm = ai_svc._llm
        raw = await llm.invoke(messages, task_type="analysis", complexity="medium")
        hotspot_text = (raw or "").strip()
    except Exception as e:
        logger.warning("AcFun 热点刷新 LLM 失败: %s", e)
        hotspot_text = (
            "【AcFun 热点参考】\n"
            "硬核：游戏速通、硬核科普、买买买\n"
            "氛围：认真且活泼、TD、AC娘表情包"
        )

    payload: dict[str, Any] = {"report": hotspot_text, "source": source_type}
    await cache.set(ACFUN_HOTSPOT_CACHE_KEY, payload, ttl=TTL_ACFUN_HOTSPOT)
    logger.info(f"AcFun 热点榜单报告已刷新并写入缓存 (Source: {source_type})")
    return hotspot_text

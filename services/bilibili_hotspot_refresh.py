"""
B站热点榜单定时任务：优先尝试通过 API 抓取 B站热门视频列表，若失败则回退到搜索，最后进行 LLM 提炼。
报告聚焦：帮助用户分析如何打造热点 IP、内容结构与风格等，供生成脑借鉴。
"""
from __future__ import annotations

import logging
import httpx
from typing import Any, List, Dict

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
1. **热门趋势**：当前 B站最火的内容类型、题材（如：知识科普、生活Vlog、鬼畜二创等）
2. **典型结构**：热门视频的标题套路、封面特点、开头 hooks、结尾互动形式
3. **创作风格**：语言特点（年轻化、有梗、弹幕文化）、情感基调
4. **可借鉴要点**：适合推广类内容、热点 IP 打造借鉴的具体写法

输出要求：用清晰的 bullet 或分点形式，便于后续生成文案时直接参考。控制在 500 字以内。"""


async def _fetch_bilibili_hot_list(limit: int = 15) -> str:
    """
    尝试从 B站 API 获取热门视频列表，并格式化为文本。
    """
    url = "https://api.bilibili.com/x/web-interface/popular?ps=20&pn=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"B站 API 请求失败: Status {resp.status_code}")
                return ""
            
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(f"B站 API 返回错误码: {data.get('code')} - {data.get('message')}")
                return ""
            
            items = data.get("data", {}).get("list", [])
            if not items:
                return ""
            
            # 格式化前 N 个结果
            lines = ["【B站当前热门视频列表】"]
            for i, item in enumerate(items[:limit], 1):
                title = item.get("title", "无标题")
                owner = item.get("owner", {}).get("name", "未知UP主")
                desc = item.get("desc", "").replace("\n", " ")[:100]  # 截取简介
                stat = item.get("stat", {})
                views = stat.get("view", 0)
                likes = stat.get("like", 0)
                
                lines.append(f"{i}. 标题：{title}")
                lines.append(f"   UP主：{owner} | 播放：{views} | 点赞：{likes}")
                lines.append(f"   简介：{desc}...")
                lines.append("")
            
            return "\n".join(lines)
            
    except Exception as e:
        logger.warning(f"B站 API 抓取异常: {e}")
        return ""


async def refresh_bilibili_hotspot_report(
    cache: SmartCache | None = None,
    ai_service: SimpleAIService | None = None,
    web_searcher: WebSearcher | None = None,
) -> str:
    """
    执行 B站热点榜单刷新：
    1. 优先尝试 API 抓取热门列表
    2. 失败则回退到 WebSearcher 搜索
    3. LLM 提炼 → 写入 Redis
    """
    cache = cache or SmartCache()
    ai_svc = ai_service or SimpleAIService()
    
    # 1. 尝试 API 抓取
    context_text = await _fetch_bilibili_hot_list()
    source_type = "API"
    
    # 2. 如果 API 失败，回退到搜索
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
        
        search_query = "B站 bilibili 热门 热搜 热门视频 2025 爆款 创作风格 热点IP"
        try:
            results = await web_searcher.search(search_query, num_results=5)
            context_text = web_searcher.format_results_as_context(results)
        except Exception as e:
            logger.warning("B站热点刷新搜索失败: %s，使用兜底", e)
            context_text = "（搜索暂不可用，请基于你对 B站热门内容的了解作答）"

    user_prompt = f"""【B站相关信息（来源：{source_type}）】
{context_text[:3000]}

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

    payload: dict[str, Any] = {"report": hotspot_text, "source": source_type}
    await cache.set(BILIBILI_HOTSPOT_CACHE_KEY, payload, ttl=TTL_BILIBILI_HOTSPOT)
    logger.info(f"B站热点榜单报告已刷新并写入缓存 (Source: {source_type})")
    return hotspot_text

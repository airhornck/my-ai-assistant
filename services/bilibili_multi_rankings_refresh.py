"""
B站多榜单定时任务：获取热门榜、每周必看、排行榜等
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from cache.smart_cache import (
    BILIBILI_MULTI_RANKINGS_CACHE_KEY,
    TTL_BILIBILI_MULTI_RANKINGS,
    SmartCache,
)
from config.search_config import get_search_config
from core.search import WebSearcher
from services.ai_service import SimpleAIService

logger = logging.getLogger(__name__)

# B站API配置
BILIBILI_APIS = {
    "popular": "https://api.bilibili.com/x/web-interface/popular?ps=20&pn=1",  # 热门榜
    "weekly": "https://api.bilibili.com/x/web-interface/popular/series/one?number={week_number}",  # 每周必看
    "ranking_all": "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all",  # 全站排行榜
    "ranking_origin": "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=origin",  # 原创榜
    "ranking_rookie": "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=rookie",  # 新人榜
}

BILIBILI_MULTI_RANKINGS_SYSTEM = """你是B站内容策略专家。根据给定的B站多个榜单数据，分析：
1. **榜单差异分析**：不同榜单（热门、每周必看、全站榜、原创榜、新人榜）的内容特点
2. **内容趋势**：当前B站最受欢迎的内容类型、风格、时长分布
3. **创作者策略**：上榜视频的创作技巧、标题套路、封面设计、互动策略
4. **行业分布**：不同行业内容在B站的表现（游戏、知识、生活、娱乐等）
5. **营销启示**：品牌如何借助B站不同榜单进行内容营销

输出要求：按榜单分类分析，每个榜单总结3-5个关键发现，最后给出综合建议。
控制在600字以内，结构清晰，便于内容创作参考。"""


async def fetch_bilibili_api(api_url: str, api_name: str) -> List[Dict]:
    """调用B站API获取榜单数据"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 处理每周必看的周数参数
            if "{week_number}" in api_url:
                from datetime import datetime, timedelta
                # 计算当前是第几周（简单实现）
                today = datetime.now()
                week_number = today.isocalendar()[1]
                api_url = api_url.format(week_number=week_number)

            resp = await client.get(api_url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"B站{api_name} API请求失败: Status {resp.status_code}")
                return []

            data = resp.json()
            if data.get("code") != 0:
                logger.warning(f"B站{api_name} API返回错误: {data.get('message')}")
                return []

            items = []
            if api_name == "weekly":
                items = data.get("data", {}).get("list", [])
            else:
                items = data.get("data", {}).get("list", data.get("data", {}).get("items", []))

            formatted_items = []
            for i, item in enumerate(items[:15], 1):
                # 统一字段名
                title = item.get("title") or item.get("name", "无标题")
                owner = item.get("owner", {}).get("name") or item.get("author", "未知UP主")
                desc = item.get("desc") or item.get("description", "")[:100]

                stat = item.get("stat", {})
                views = stat.get("view", 0) or item.get("play", 0)
                likes = stat.get("like", 0) or item.get("like", 0)
                coins = stat.get("coin", 0)
                favorites = stat.get("favorite", 0)
                shares = stat.get("share", 0)

                # 判断内容类型
                tid = item.get("tid", 0)
                content_type = "其他"
                if tid in [17, 171]:  # 单机游戏、电子竞技
                    content_type = "游戏"
                elif tid in [27, 124]:  # 数码、科技
                    content_type = "科技"
                elif tid in [21, 136]:  # 日常、生活
                    content_type = "生活"
                elif tid in [157, 158]:  # 时尚、美妆
                    content_type = "时尚"
                elif tid in [181, 182]:  # 影视、娱乐
                    content_type = "娱乐"
                elif tid in [201, 207]:  # 科学、知识
                    content_type = "知识"

                formatted_items.append({
                    "rank": i,
                    "title": title,
                    "up主": owner,
                    "简介": desc,
                    "播放量": views,
                    "点赞": likes,
                    "投币": coins,
                    "收藏": favorites,
                    "分享": shares,
                    "内容类型": content_type,
                    "榜单": api_name
                })

            return formatted_items

    except Exception as e:
        logger.warning(f"B站{api_name} API抓取异常: {e}")
        return []


async def refresh_bilibili_multi_rankings_report(
        cache: SmartCache | None = None,
        ai_service: SimpleAIService | None = None,
        web_searcher: WebSearcher | None = None,
) -> str:
    """
    执行B站多榜单刷新：
    1. 并行获取多个榜单数据
    2. 失败则回退到搜索
    3. LLM分析处理 → 写入缓存
    """
    cache = cache or SmartCache()
    ai_svc = ai_service or SimpleAIService()

    # 并行获取所有榜单
    tasks = []
    for api_name, api_url in BILIBILI_APIS.items():
        tasks.append(fetch_bilibili_api(api_url, api_name))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 整理结果
    all_rankings = {}
    for api_name, result in zip(BILIBILI_APIS.keys(), results):
        if isinstance(result, Exception):
            logger.warning(f"获取{api_name}榜单失败: {result}")
            all_rankings[api_name] = []
        else:
            all_rankings[api_name] = result

    # 构建LLM输入
    context_parts = []
    for api_name, items in all_rankings.items():
        if not items:
            continue

        context_parts.append(f"【B站{api_name}榜单】")
        for item in items[:5]:  # 每个榜单取前5
            context_parts.append(
                f"第{item['rank']}名：{item['title']}\n"
                f"  UP主：{item['up主']} | 播放：{item['播放量']} | 点赞：{item['点赞']}\n"
                f"  类型：{item['内容类型']} | 投币：{item['投币']} | 收藏：{item['收藏']}"
            )
        context_parts.append("")

    context_text = "\n".join(context_parts)

    if not context_text.strip():
        # 如果API都失败，使用搜索作为后备
        source_type = "Search"
        if web_searcher is None:
            cfg = get_search_config()
            web_searcher = WebSearcher(
                api_key=cfg.get("baidu_api_key"),
                provider=cfg.get("provider", "mock"),
                base_url=cfg.get("baidu_base_url"),
                top_k=cfg.get("baidu_top_k", 20),
            )

        try:
            search_query = "B站 bilibili 热门榜 每周必看 排行榜 2025 爆款视频 创作趋势"
            results = await web_searcher.search(search_query, num_results=8)
            context_text = web_searcher.format_results_as_context(results)
        except Exception as e:
            logger.warning("B站多榜单搜索失败: %s，使用兜底", e)
            context_text = "（B站榜单获取暂不可用，请基于你对B站热门内容的了解作答）"
    else:
        source_type = "API"

    user_prompt = f"""【B站多榜单数据（来源：{source_type}）】
{context_text[:3500]}

请分析B站不同榜单的内容特点、趋势和创作策略，为内容创作提供参考。"""

    messages = [
        SystemMessage(content=BILIBILI_MULTI_RANKINGS_SYSTEM),
        HumanMessage(content=user_prompt),
    ]

    try:
        llm = ai_svc._llm
        raw = await llm.invoke(messages, task_type="analysis", complexity="medium")
        rankings_report = (raw or "").strip()
    except Exception as e:
        logger.warning("B站多榜单分析LLM失败: %s", e)
        rankings_report = (
            "【B站多榜单分析报告】\n"
            "1. 热门榜：反映实时热度，生活、游戏类内容占主导\n"
            "2. 每周必看：优质深度内容，知识科普类表现突出\n"
            "3. 全站榜：综合热度指标，头部效应明显\n"
            "4. 原创榜：鼓励原创内容，新人有机会突围\n"
            "5. 新人榜：新UP主成长路径，关注互动率指标\n"
            "营销启示：根据品牌调性选择合适榜单进行内容投放"
        )

    # 存储数据
    payload = {
        "report": rankings_report,
        "raw_data": all_rankings,
        "timestamp": datetime.now().isoformat(),
        "source": source_type
    }

    await cache.set(BILIBILI_MULTI_RANKINGS_CACHE_KEY, payload, ttl=TTL_BILIBILI_MULTI_RANKINGS)
    logger.info(f"B站多榜单报告已刷新，涵盖{len([v for v in all_rankings.values() if v])}个榜单")
    return rankings_report
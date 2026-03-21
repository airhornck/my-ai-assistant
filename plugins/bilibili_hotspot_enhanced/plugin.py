"""
行业新闻与B站榜单插件：分析脑的定时插件。
声明类型为定时插件，刷新逻辑由脑级插件中心管理。
"""
from __future__ import annotations

import logging
from typing import Any

from cache.smart_cache import (
    INDUSTRY_NEWS_CACHE_KEY,
    BILIBILI_MULTI_RANKINGS_CACHE_KEY,
    SmartCache,
)
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_SCHEDULED

logger = logging.getLogger(__name__)

FALLBACK_INDUSTRY_REPORT = """【行业新闻分析报告】
科技：AI大模型持续火热，关注AI应用落地
金融：政策利好频出，关注数字经济相关板块
娱乐：影视作品热度分化，关注口碑传播效应
游戏：新游发布频繁，关注用户留存策略
汽车：新能源车竞争加剧，关注智能化升级
教育：职业教育受关注，关注技能培训需求
营销启示：结合行业热点进行内容创作，把握趋势红利"""

FALLBACK_BILIBILI_REPORT = """【B站多榜单分析报告】
1. 热门榜：反映实时热度，生活、游戏类内容占主导
2. 每周必看：优质深度内容，知识科普类表现突出
3. 全站榜：综合热度指标，头部效应明显
4. 原创榜：鼓励原创内容，新人有机会突围
5. 新人榜：新UP主成长路径，关注互动率指标
营销启示：根据品牌调性选择合适榜单进行内容投放"""


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """向分析脑插件中心注册行业新闻与B站榜单插件。依赖均从 config 注入。类型：定时插件，刷新由插件中心调度。"""
    cache = config.get("cache") or config.get("smart_cache")
    ai_service = config.get("ai_service")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """获取插件输出：读缓存，未命中则返回兜底。"""
        existing_analysis = context.get("analysis") or {}

        # 获取行业新闻
        industry_report = FALLBACK_INDUSTRY_REPORT
        bilibili_report = FALLBACK_BILIBILI_REPORT

        if cache is not None:
            try:
                # 获取行业新闻
                industry_payload = await cache.get(INDUSTRY_NEWS_CACHE_KEY)
                if isinstance(industry_payload, dict) and industry_payload.get("report"):
                    industry_report = industry_payload["report"].strip()

                # 获取B站多榜单
                bilibili_payload = await cache.get(BILIBILI_MULTI_RANKINGS_CACHE_KEY)
                if isinstance(bilibili_payload, dict) and bilibili_payload.get("report"):
                    bilibili_report = bilibili_payload["report"].strip()
            except Exception as e:
                logger.debug("行业新闻/B站榜单缓存读取失败: %s，使用兜底", e)

        if not isinstance(existing_analysis, dict):
            existing_analysis = {}

        return {
            "analysis": {
                **existing_analysis,
                "industry_news": industry_report,
                "bilibili_multi_rankings": bilibili_report
            }
        }

    async def refresh() -> None:
        """定时刷新：并行获取行业新闻和B站榜单"""
        try:
            from services.industry_news_refresh import refresh_industry_news_report
            from services.bilibili_multi_rankings_refresh import refresh_bilibili_multi_rankings_report

            # 并行执行两个刷新任务
            import asyncio
            tasks = [
                refresh_industry_news_report(cache=cache, ai_service=ai_service),
                refresh_bilibili_multi_rankings_report(cache=cache, ai_service=ai_service)
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("行业新闻与B站榜单刷新完成")

        except Exception as e:
            logger.error("行业新闻与B站榜单刷新失败: %s", e)

    plugin_center.register_plugin(
        "industry_news_bilibili_rankings",
        PLUGIN_TYPE_SCHEDULED,
        get_output=get_output,
        refresh_func=refresh,
        schedule_config={"interval_hours": 4},  # 每4小时刷新一次
    )
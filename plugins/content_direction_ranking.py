"""
内容方向榜单插件（分析脑级插件，对应 Lumina「已过滤的内容方向榜单」）：
基于 IP 画像与各平台热点，输出已过滤并排序的内容方向列表，
每项含适配度、热度趋势、风险等级、角度建议、标题模板。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage

from cache.smart_cache import (
    BILIBILI_HOTSPOT_CACHE_KEY,
    DOUYIN_HOTSPOT_CACHE_KEY,
    XIAOHONGSHU_HOTSPOT_CACHE_KEY,
    ACFUN_HOTSPOT_CACHE_KEY,
)
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

PLUGIN_NAME = "content_direction_ranking"

HOTSPOT_KEYS = {
    "bilibili": BILIBILI_HOTSPOT_CACHE_KEY,
    "douyin": DOUYIN_HOTSPOT_CACHE_KEY,
    "xiaohongshu": XIAOHONGSHU_HOTSPOT_CACHE_KEY,
    "acfun": ACFUN_HOTSPOT_CACHE_KEY,
}


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """注册内容方向榜单插件（实时）。"""
    cache = config.get("cache")
    ai_service = config.get("ai_service")
    platform_rules = config.get("platform_rules")  # 可选，用于风险词

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """
        基于画像与热点生成已过滤的内容方向榜单：
        适配度、热度、风险等级、3–5 个切入角度、标题模板。
        """
        if not ai_service or not cache:
            return {}

        request = context.get("request")
        preference_context = context.get("preference_context", "")
        if not preference_context and request:
            brand = getattr(request, "brand_name", "") or ""
            product = getattr(request, "product_desc", "") or ""
            preference_context = f"品牌：{brand}；产品：{product}"
        platform = (getattr(request, "topic", "") or context.get("platform", "") or "通用").strip().lower()
        if platform not in HOTSPOT_KEYS:
            platform = "xiaohongshu"

        # 1. 拉取热点摘要
        hotspot_text = ""
        try:
            key = HOTSPOT_KEYS.get(platform, XIAOHONGSHU_HOTSPOT_CACHE_KEY)
            payload = await cache.get(key)
            if payload and isinstance(payload, dict) and payload.get("report"):
                hotspot_text = (payload.get("report") or "")[:800]
        except Exception as e:
            logger.debug("content_direction_ranking 读取热点缓存失败: %s", e)

        # 2. 调用 AI 生成带适配度/热度/风险/角度/标题模板的榜单
        llm = ai_service.router.powerful_model
        prompt = f"""
你是一位个人 IP 内容策划师。根据用户画像与当前平台热点，生成「已过滤的内容方向榜单」。
要求：每条方向需包含适配度评分(0-100)、热度趋势(up/stable/down)、风险等级(low/medium/high)、
3-5 个切入角度、2-3 个可直接使用的标题模板；高风险方向需在 risk_warning 中简要说明。

【用户画像】
{preference_context or "未提供，按通用创作者处理"}

【平台】
{platform}

【当前热点摘要】
{hotspot_text or "暂无热点数据，请基于通用趋势给出建议"}

请只输出一个 JSON 数组，不要其他文字。格式示例：
[
  {{
    "title": "方向名称",
    "adaptation_score": 85,
    "heat_trend": "up",
    "risk_level": "low",
    "angles": ["角度1", "角度2", "角度3"],
    "title_templates": ["标题模板1", "标题模板2"],
    "reason": "推荐理由",
    "risk_warning": ""
  }},
  ...
]
数量 5–8 条，按适配度从高到低排序。risk_level 为 high 时 risk_warning 必填。
"""
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content.strip()
            for prefix in ("```json", "```"):
                if text.startswith(prefix):
                    text = text[len(prefix) :].strip()
            if text.endswith("```"):
                text = text[: text.rfind("```")].strip()
            items: List[Dict[str, Any]] = json.loads(text)
        except Exception as e:
            logger.warning("content_direction_ranking AI 解析失败: %s", e)
            items = []

        # 3. 统一字段名供能力接口使用
        result = []
        for i, row in enumerate(items[:15]):
            if not isinstance(row, dict):
                continue
            result.append({
                "rank": i + 1,
                "title": row.get("title", ""),
                "title_suggestion": row.get("title", ""),
                "adaptation_score": row.get("adaptation_score"),
                "heat_trend": row.get("heat_trend", "stable"),
                "risk_level": row.get("risk_level", "low"),
                "angles": row.get("angles", []),
                "title_templates": row.get("title_templates", []),
                "reason": row.get("reason", ""),
                "risk_warning": row.get("risk_warning", ""),
                "core_angle": (row.get("angles") or [""])[0] if row.get("angles") else "",
            })

        return {
            "analysis": {
                **context.get("analysis", {}),
                PLUGIN_NAME: {
                    "items": result,
                    "platform": platform,
                },
            },
        }

    plugin_center.register_plugin(
        PLUGIN_NAME,
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

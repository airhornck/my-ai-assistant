"""
选题插件（分析脑级插件）：
1. 定时任务 (refresh)：爬取各平台（小红书、抖音、B站、视频号）爆款账号，提取模版与热点并缓存。
2. 实时输出 (get_output)：结合用户画像（从 context 获取）与缓存的热点/模版，生成选题推荐。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Any, List, Dict, Optional

import aiohttp
from langchain_core.messages import HumanMessage

from cache.smart_cache import (
    BILIBILI_HOTSPOT_CACHE_KEY,
    DOUYIN_HOTSPOT_CACHE_KEY,
    XIAOHONGSHU_HOTSPOT_CACHE_KEY,
    ACFUN_HOTSPOT_CACHE_KEY,
)
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_SCHEDULED

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------
CACHE_KEY_TEMPLATE_PREFIX = "topic_templates:"
CACHE_KEY_HOTSPOT_PREFIX = "hot_searches:" # 旧版模拟热点键前缀，逐步废弃
# 平台定义：现在大部分已有独立插件支持
PLATFORMS = ["xiaohongshu", "douyin", "bilibili", "acfun", "channels"] 

# 模拟的目标账号列表（实际生产中应从数据库读取或通过搜索发现）
TARGET_ACCOUNTS = {
    p: {
        "head": [f"{p}_head_{i}" for i in range(5)],
        "waist": [f"{p}_waist_{i}" for i in range(5)],
        "viral": [f"{p}_viral_{i}" for i in range(5)],
    }
    for p in PLATFORMS
}

def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """
    向分析脑插件中心注册选题插件。
    类型：SCHEDULED (定时任务负责爬取/更新缓存；get_output 负责实时推荐)
    
    【能力重构说明】
    - B站、抖音、小红书、A站：直接复用对应热点插件的真实榜单数据。
    - 视频号 (channels)：暂维持模拟/爬取逻辑，未来建议拆分为独立插件。
    """
    cache = config.get("cache")
    ai_service = config.get("ai_service")
    memory_service = config.get("memory_service")  # 可选，若 context 中已含画像则无需

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """
        实时输出：
        1. 从 context 获取用户画像/请求信息。
        2. 读取 Redis 缓存的模版与热点（自动识别平台源）。
        3. 调用 AI 生成推荐选题。
        """
        if not ai_service or not cache:
            return {}

        # 1. 解析上下文
        request = context.get("request") # ProcessedInput 对象或 dict
        
        # 尝试从 context 中提取画像信息
        user_profile_context = context.get("preference_context", "")
        if not user_profile_context and request:
            brand = getattr(request, "brand_name", "") or ""
            product = getattr(request, "product_desc", "") or ""
            user_profile_context = f"品牌：{brand}；产品：{product}"

        content_type = "通用"
        if request:
            topic = getattr(request, "topic", "")
            if topic:
                content_type = topic

        # 2. 获取 Redis 中的模版与热点
        context_parts = []
        
        # A. 获取真实热点 (跨插件复用)
        # 映射：平台 -> 缓存键
        real_hotspot_map = {
            "bilibili": BILIBILI_HOTSPOT_CACHE_KEY,
            "douyin": DOUYIN_HOTSPOT_CACHE_KEY,
            "xiaohongshu": XIAOHONGSHU_HOTSPOT_CACHE_KEY,
            "acfun": ACFUN_HOTSPOT_CACHE_KEY,
        }

        for platform_name, cache_key in real_hotspot_map.items():
            try:
                payload = await cache.get(cache_key)
                if payload and isinstance(payload, dict):
                    report = payload.get("report", "")
                    if report:
                        # 截取部分以免 Prompt 过长，添加来源标识
                        context_parts.append(f"【{platform_name}真实热点与趋势】\n{report[:300]}...") 
            except Exception as e:
                logger.warning("TopicSelectionPlugin: 读取 %s 热点缓存失败: %s", platform_name, e)

        # B. 获取其他平台模拟/爬取热点 (如 channels)
        # 仅针对不在 real_hotspot_map 中的平台
        for p in PLATFORMS:
            if p in real_hotspot_map:
                continue
                
            hot = await cache.get(f"{CACHE_KEY_HOTSPOT_PREFIX}{p}")
            tpl = await cache.get(f"{CACHE_KEY_TEMPLATE_PREFIX}{p}")
            if hot:
                hot_list = hot if isinstance(hot, list) else str(hot).split(",")
                context_parts.append(f"【{p}热点】：{', '.join(hot_list[:5])}")
            if tpl and isinstance(tpl, list):
                samples = random.sample(tpl, min(len(tpl), 2))
                for s in samples:
                    context_parts.append(f"【{p}模版参考】标题模式：{s.get('title_pattern')}；结构：{s.get('content_structure')}")

        market_context_str = "\n".join(context_parts)

        # 3. 调用 AI (powerful_model) 生成推荐
        llm = ai_service.router.powerful_model
        
        prompt = f"""
你是一个专业的爆款选题策划师。请根据以下信息，为用户推荐 3 个高潜力的选题。

【用户画像/偏好】：
{user_profile_context}

【创作方向】：{content_type}

【当前市场热点与爆款模版】：
{market_context_str}

请输出 3 个推荐选题，JSON 格式：
[
  {{
    "title_suggestion": "标题建议",
    "core_angle": "核心切入点",
    "content_outline": "简要内容框架",
    "reason": "推荐理由（结合了哪个热点或模版）"
  }},
  ...
]
"""
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            
            recommendations = json.loads(text)
            return {"analysis": {**context.get("analysis", {}), "topic_selection": recommendations}}
            
        except Exception as e:
            logger.error("TopicSelectionPlugin: 选题推荐生成失败: %s", e)
            return {}

    async def refresh() -> None:
        """
        定时任务：爬取其他平台内容（B站、抖音、小红书、A站由各自独立插件负责）。
        """
        if not cache or not ai_service:
            logger.warning("TopicSelectionPlugin: refresh 跳过，缺少 cache 或 ai_service")
            return

        logger.info("TopicSelectionPlugin: 开始定时爬取任务 (补充平台)...")
        
        # 使用轻量级模型提取模版
        fast_llm = ai_service.router.fast_model
        
        # 仅处理未独立插件化的平台
        independent_platforms = ["bilibili", "douyin", "xiaohongshu", "acfun"]
        target_platforms = [p for p in PLATFORMS if p not in independent_platforms]
        
        for platform in target_platforms:
            try:
                # A. 爬虫引擎 (模拟)
                contents = await _crawl_platform(platform)
                
                # B. 爆款模版抽取
                if contents:
                    templates = await _extract_templates(contents, platform, fast_llm)
                    await cache.set(f"{CACHE_KEY_TEMPLATE_PREFIX}{platform}", templates, ttl=86400)
                
                # C. 热点采集
                hot_searches = await _fetch_hot_searches(platform)
                await cache.set(f"{CACHE_KEY_HOTSPOT_PREFIX}{platform}", hot_searches, ttl=3600)
                
            except Exception as e:
                logger.error("TopicSelectionPlugin: 平台 %s 任务失败: %s", platform, e, exc_info=True)
                
        logger.info("TopicSelectionPlugin: 定时爬取任务完成")

    # 注册插件
    plugin_center.register_plugin(
        "topic_selection",
        PLUGIN_TYPE_SCHEDULED,
        get_output=get_output,
        refresh_func=refresh,
        schedule_config={"interval_hours": 6},
    )

# ---------------------------------------------------------------------------
# 内部辅助函数 (爬虫与提取)
# ---------------------------------------------------------------------------

async def _crawl_platform(platform: str) -> List[dict]:
    """模拟爬取平台内容。"""
    # 实际应包含 aiohttp 请求逻辑，这里简化为模拟数据返回
    # 模拟网络延迟
    await asyncio.sleep(random.uniform(0.5, 1.5))
    
    return [
        {
            "title": f"模拟爆款标题_{platform}_{i}",
            "content": f"这是一篇关于{platform}的爆款内容，包含详细的痛点分析和解决方案...",
            "platform": platform,
            "url": f"http://{platform}.com/post/{i}"
        }
        for i in range(5)
    ]

async def _extract_templates(contents: List[dict], platform: str, llm: Any) -> List[dict]:
    """使用 AI 提取模版。"""
    templates = []
    # 仅采样前 3 条以节省 token
    for content in contents[:3]:
        try:
            prompt = f"""
请分析以下爆款内容，提取其通用模版：
标题：{content['title']}
正文：{content['content'][:300]}...

请输出 JSON 格式（不要 Markdown），包含：
- title_pattern: 标题模式
- content_structure: 正文结构
"""
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content.strip()
            if text.startswith("```json"):
                text = text[7:-3]
            elif text.startswith("```"):
                text = text[3:-3]
            
            data = json.loads(text)
            templates.append({
                "platform": platform,
                "title_pattern": data.get("title_pattern", ""),
                "content_structure": data.get("content_structure", ""),
            })
        except Exception:
            pass
    return templates

async def _fetch_hot_searches(platform: str) -> List[str]:
    """模拟获取热搜。"""
    await asyncio.sleep(0.5)
    return [f"{platform}热点_{i}" for i in range(1, 11)]

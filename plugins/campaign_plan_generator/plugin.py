"""
活动方案生成插件：生成脑实时插件。
基于 analysis 中的 campaign_context、angle、reason 等调用 LLM 生成完整活动方案（Markdown）。
模型由插件中心 config["models"]["campaign_plan_generator"] 管理；未配置时回退 ai_service.router。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from cache.smart_cache import build_fingerprint_key
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

DEFAULT_CACHE_KEY_PREFIX = "plugin:generation:campaign_plan:"
DEFAULT_CACHE_TTL_SECONDS = 0


def _get_config(config: dict[str, Any]) -> dict[str, Any]:
    plugin_cfg = config.get("campaign_plan_generator") or {}
    return {
        "cache_key_prefix": plugin_cfg.get("cache_key_prefix") or DEFAULT_CACHE_KEY_PREFIX,
        "cache_ttl_seconds": plugin_cfg.get("cache_ttl_seconds", DEFAULT_CACHE_TTL_SECONDS),
    }


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """向生成脑插件中心注册活动方案生成插件。模型从插件中心 config 读取。"""
    cache = config.get("cache")
    ai_service = config.get("ai_service")
    models = config.get("models") or {}
    model_cfg = models.get("campaign_plan_generator")
    client = None
    if model_cfg and model_cfg.get("model"):
        try:
            client = ChatOpenAI(
                model=model_cfg.get("model", "qwen3-max"),
                base_url=model_cfg.get("base_url"),
                api_key=model_cfg.get("api_key"),
                temperature=model_cfg.get("temperature", 0.7),
                max_tokens=model_cfg.get("max_tokens", 8192),
            )
            logger.info("campaign_plan_generator 使用插件中心模型: %s", model_cfg.get("model"))
        except Exception as e:
            logger.warning("campaign_plan_generator 模型初始化失败，将使用 ai_service: %s", e)
    cfg = _get_config(config)

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """若 analysis 含 campaign_context 则生成活动方案；否则返回空 dict 表示未处理。"""
        analysis = context.get("analysis") or {}
        if not isinstance(analysis, dict):
            return {}
        campaign_context = analysis.get("campaign_context") or analysis.get("methodology") or ""
        if not (campaign_context and campaign_context.strip()):
            return {}
        topic = context.get("topic") or ""
        raw_query = context.get("raw_query") or ""
        brand = analysis.get("brand_name") or ""
        product = analysis.get("product_desc") or ""
        angle = analysis.get("angle") or ""
        reason = analysis.get("reason") or ""
        memory_context = context.get("memory_context") or "（暂无用户记忆）"

        # 可选：按 analysis 指纹缓存
        if cfg["cache_ttl_seconds"] > 0 and cache is not None:
            fp = {
                "campaign_context": (campaign_context or "")[:500],
                "topic": topic,
                "brand": brand,
                "product": product,
            }
            key = build_fingerprint_key(cfg["cache_key_prefix"], fp)
            try:
                payload = await cache.get(key)
                if isinstance(payload, dict) and payload.get("content"):
                    return {"content": payload["content"]}
            except Exception as e:
                logger.debug("campaign_plan_generator 缓存读取失败: %s", e)

        system_prompt = (
            "你是营销活动策划专家。根据「行业知识」「用户记忆」和「本次请求」生成营销活动方案。"
            "若下方有【参考案例】，请优先参考其结构与要点，结合本次请求进行改写或填空，形成贴合客户需求的方案（内容日历、投放计划、预算分配等）。"
        )
        user_prompt = f"""【本次请求】
品牌：{brand}
产品：{product}
目标：{topic}

【行业知识】
{campaign_context}

【用户记忆】
{memory_context}

请输出营销活动方案（Markdown 格式）。若上方有参考案例，请以其为基础改写或填空，避免从零堆砌。"""
        if angle or reason:
            user_prompt += f"\n\n【分析要点】{angle}\n{reason}"

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        content = ""
        try:
            if client is not None:
                response = await client.ainvoke(messages)
                content = (response.content or "").strip()
            elif ai_service is not None:
                router = await ai_service.router.route(task_type="generation", prompt_complexity="high")
                response = await router.ainvoke(messages)
                content = (response.content or "").strip()
            else:
                logger.warning("campaign_plan_generator 未配置模型且未注入 ai_service")
                return {}
        except Exception as e:
            logger.warning("campaign_plan_generator LLM 调用失败: %s", e, exc_info=True)
            return {}

        if cfg["cache_ttl_seconds"] > 0 and cache is not None and content:
            fp = {
                "campaign_context": (campaign_context or "")[:500],
                "topic": topic,
                "brand": brand,
                "product": product,
            }
            key = build_fingerprint_key(cfg["cache_key_prefix"], fp)
            try:
                await cache.set(key, {"content": content}, ttl=cfg["cache_ttl_seconds"])
            except Exception as e:
                logger.debug("campaign_plan_generator 缓存写入失败: %s", e)

        return {"content": content}
    plugin_center.register_plugin(
        "campaign_plan_generator",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

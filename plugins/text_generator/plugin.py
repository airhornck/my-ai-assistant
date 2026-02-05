"""
文本生成插件：生成脑实时插件，使用 qwen3-max（或插件中心 config 指定模型）。
模型配置由插件中心 config["models"]["text_generator"] 管理，未配置则回退 get_model_config("generation_text")。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.api_config import get_model_config
from config.media_specs import build_user_prompt, resolve_media_spec
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """向生成脑插件中心注册文本生成插件。模型从 config["models"]["text_generator"] 或 generation_text 读取。"""
    models = config.get("models") or {}
    model_cfg = models.get("text_generator") or get_model_config("generation_text")
    client = ChatOpenAI(
        model=model_cfg.get("model", "qwen3-max"),
        base_url=model_cfg.get("base_url"),
        api_key=model_cfg.get("api_key"),
        temperature=model_cfg.get("temperature", 0.7),
        max_tokens=model_cfg.get("max_tokens", 8192),
    )
    logger.info("text_generator 插件已加载, model=%s", model_cfg.get("model", "qwen3-max"))

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """根据 analysis、topic、raw_query 生成推广文案；若 output_type=rewrite 且 source_content 存在则为对上文的风格改写。"""
        output_type = context.get("output_type") or "text"
        source_content = (context.get("source_content") or "").strip()
        if output_type == "rewrite" and source_content:
            # 对上文内容的风格/平台改写：保持核心信息不变，仅调整语气、结构与平台特色
            platform = (context.get("topic") or "").strip() or "目标平台"
            system_prompt = (
                "你是一位熟悉各平台风格的文案专家。请将用户提供的已有内容改写成指定平台的风格，"
                "保持核心信息、卖点与事实不变，仅调整语气、句式、梗与平台特色（如 B站 可更轻松、有梗，小红书偏种草、emoji 等）。"
                "直接输出改写后的完整内容，不要解释。"
            )
            user_prompt = f"""【待改写内容】
{source_content[:5000]}

【要求】
请将以上内容改写成「{platform}」的风格，保持核心信息不变，直接输出改写后的完整内容。"""
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            try:
                response = await client.ainvoke(messages)
                content = (response.content or "").strip()
                return {"content": content}
            except Exception as e:
                logger.warning("text_generator 插件改写失败: %s", e, exc_info=True)
                return {}
        # 常规生成
        analysis = context.get("analysis") or {}
        if not isinstance(analysis, dict):
            analysis = {}
        topic = context.get("topic") or ""
        raw_query = context.get("raw_query") or ""
        session_document_context = context.get("session_document_context") or ""
        analysis_text = (
            f"关联度得分：{analysis.get('semantic_score', 0)}；"
            f"推荐切入点：{analysis.get('angle', '')}；"
            f"分析理由：{analysis.get('reason', '')}"
        )
        hotspot = analysis.get("bilibili_hotspot")
        if hotspot and isinstance(hotspot, str) and hotspot.strip():
            analysis_text += f"\n\n【B站热点参考（请借鉴其文章结构与创作风格）】\n{hotspot.strip()}"
        spec = resolve_media_spec(topic=topic, raw_query=raw_query)
        user_prompt = build_user_prompt(spec, analysis_text, topic, raw_query)
        if session_document_context.strip():
            user_prompt = (
                "【参考补充（已从用户提供的文档/链接中提取）】\n"
                f"{session_document_context.strip()}\n\n"
                + user_prompt
            )
        messages = [
            SystemMessage(content=spec.system_prompt),
            HumanMessage(content=user_prompt),
        ]
        try:
            response = await client.ainvoke(messages)
            content = (response.content or "").strip()
            return {"content": content}
        except Exception as e:
            logger.warning("text_generator 插件生成失败: %s", e, exc_info=True)
            return {}

    plugin_center.register_plugin(
        "text_generator",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

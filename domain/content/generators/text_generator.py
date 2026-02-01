"""
文本生成模块：生成文案、脚本等。
配置从 config.api_config 的 generation_text 接口获取。
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

# 统一接口配置入口：config/api_config，引用 generation_text 接口
from config.api_config import get_model_config
from config.media_specs import resolve_media_spec, build_user_prompt

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class TextGenerator:
    """文本生成模块：调用 generation_text 角色配置的模型生成推广文案、脚本等。"""

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or get_model_config("generation_text")
        self._client = ChatOpenAI(
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            temperature=cfg.get("temperature", 0.7),
            max_tokens=cfg.get("max_tokens", 8192),
        )
        logger.info("TextGenerator 已初始化, model=%s", cfg["model"])

    async def generate(
        self,
        analysis: str | dict[str, Any],
        topic: str = "",
        raw_query: str = "",
        session_document_context: str = "",
    ) -> str:
        """生成推广文案。"""
        if isinstance(analysis, dict):
            analysis_text = (
                f"关联度得分：{analysis.get('semantic_score', 0)}；"
                f"推荐切入点：{analysis.get('angle', '')}；"
                f"分析理由：{analysis.get('reason', '')}"
            )
            # B站热点参考：若插件提供了结构与风格，供生成时借鉴
            hotspot = analysis.get("bilibili_hotspot")
            if hotspot and isinstance(hotspot, str) and hotspot.strip():
                analysis_text += f"\n\n【B站热点参考（请借鉴其文章结构与创作风格）】\n{hotspot.strip()}"
        else:
            analysis_text = analysis or ""

        spec = resolve_media_spec(topic=topic, raw_query=raw_query)
        user_prompt = build_user_prompt(spec, analysis_text, topic, raw_query)
        if session_document_context and session_document_context.strip():
            user_prompt = (
                "【参考补充（已从用户提供的文档/链接中提取，仅用于丰富主推广对象的表述）】\n"
                f"{session_document_context.strip()}\n\n"
                + user_prompt
            )

        messages = [
            SystemMessage(content=spec.system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = await self._client.ainvoke(messages)
        return (response.content or "").strip()

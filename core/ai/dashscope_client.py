"""
阿里云 DashScope（百炼）LLM 实现。
按任务类型映射到对应角色配置，从 config.api_config 统一获取。
可替换为其他 ILLMClient 实现（如 OpenAI、智谱等）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

# 统一接口配置入口：config/api_config，引用 intent/strategy/analysis/evaluation
from config.api_config import get_model_config

logger = logging.getLogger(__name__)

# task_type -> 模型角色
_TASK_TO_ROLE: dict[str, str] = {
    "chat_reply": "intent",
    "planning": "strategy",
    "evaluation": "evaluation",
    "analysis": "analysis",
    "chat": "strategy",  # 默认聊天
}


class DashScopeLLMClient:
    """
    阿里云 DashScope 实现 ILLMClient。
    按 task_type 映射到 MODEL_ROLES 中的角色配置，各模块使用各自模型与参数。
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        self._override = config or {}
        self._clients: dict[str, ChatOpenAI] = {}

    def _get_client(self, role: str) -> ChatOpenAI:
        """按角色获取 ChatOpenAI 实例（懒加载）。"""
        if role not in self._clients:
            cfg = get_model_config(role, override=self._override)
            self._clients[role] = ChatOpenAI(
                model=cfg["model"],
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
                temperature=cfg.get("temperature", 0.5),
                max_tokens=cfg.get("max_tokens", 8192),
            )
        return self._clients[role]

    def _resolve_role(self, task_type: str, complexity: str) -> str:
        """根据 task_type 和 complexity 解析模型角色。"""
        role = _TASK_TO_ROLE.get(task_type)
        if role:
            return role
        # 未映射时：高复杂度用策略脑，否则用意图
        return "strategy" if complexity == "high" else "intent"

    async def invoke(
        self,
        messages: list | str,
        *,
        task_type: str = "chat",
        complexity: str = "medium",
    ) -> str:
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]
        elif not isinstance(messages, list):
            messages = [HumanMessage(content=str(messages))]
        role = self._resolve_role(task_type, complexity)
        client = self._get_client(role)
        fallback_role = "intent" if role == "strategy" else "strategy"
        fallback = self._get_client(fallback_role)
        try:
            response = await client.ainvoke(messages)
        except Exception as e:
            logger.warning("主模型 %s 调用失败，降级到 %s: %s", role, fallback_role, e, exc_info=True)
            response = await fallback.ainvoke(messages)
        return (response.content or "").strip() if hasattr(response, "content") else str(response).strip()

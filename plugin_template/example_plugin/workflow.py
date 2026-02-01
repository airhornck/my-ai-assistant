"""
示例插件工作流：展示如何从 config 获取 MemoryService、AIService，并遵守 State 约定。

【访问共享服务】
- ai_service：从 config["ai_service"] 获取，用于调用大模型（如 client.ainvoke）。
- memory_service：从 config.get("memory_service") 获取，未传入时自行 MemoryService()。
  用于 get_memory_for_analyze(user_id, brand_name, product_desc, topic, tags_override)。

【State 约定】
- 入参 state 由 meta_workflow 编排传入，包含 user_input, analysis, content, session_id,
  user_id, evaluation, need_revision, stage_durations, analyze_cache_hit, used_tags。
- 节点返回必须为增量更新，包含上述字段，避免上游合并时丢失。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from services.ai_service import SimpleAIService
from domain.memory import MemoryService

logger = logging.getLogger(__name__)


def build_workflow(config: dict[str, Any] | None = None) -> Any:
    """
    构建示例插件工作流：读取 user_input → 拉取用户记忆 → 调用 AI 生成简短小结 → 返回 State 兼容结果。
    """
    config = config or {}

    # ---------- 从 config 获取共享服务（遵守模板约定）----------
    ai_svc: SimpleAIService = config.get("ai_service")
    if ai_svc is None:
        ai_svc = SimpleAIService()
    memory_svc: MemoryService = config.get("memory_service")
    if memory_svc is None:
        memory_svc = MemoryService()

    async def _example_node(state: dict) -> dict:
        """
        示例节点：使用 MemoryService 获取用户上下文，使用 AIService 生成内容，并返回 State 兼容字典。
        """
        t0 = time.perf_counter()
        user_id = state.get("user_id") or ""
        user_input = state.get("user_input") or ""

        try:
            data = json.loads(user_input) if isinstance(user_input, str) else {}
        except (TypeError, json.JSONDecodeError):
            data = {}
        brand = data.get("brand_name", "")
        product = data.get("product_desc", "")
        topic = data.get("topic", "")
        tags_override = list(data["tags"]) if isinstance(data.get("tags"), list) and data.get("tags") else None

        # 使用共享 MemoryService 获取用户记忆（遵守 MetaState/State 上下文）
        try:
            memory = await memory_svc.get_memory_for_analyze(
                user_id=user_id,
                brand_name=brand,
                product_desc=product,
                topic=topic,
                tags_override=tags_override,
            )
            preference_context = memory.get("preference_context", "") or "（暂无用户记忆）"
            effective_tags = memory.get("effective_tags", [])
        except Exception as e:
            logger.warning("example_plugin MemoryService 查询失败: %s", e, exc_info=True)
            preference_context = "（暂无用户记忆）"
            effective_tags = []

        # 使用共享 AIService 调用大模型
        system_prompt = "你是一位简洁的营销助手。根据「用户记忆」和「本次请求」用 1～2 句话输出一条简短小结，不要多余格式。"
        user_prompt = f"【本次请求】品牌：{brand}，产品：{product}，话题：{topic}\n【用户记忆】\n{preference_context[:800]}"
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        try:
            response = await ai_svc.client.ainvoke(messages)
            new_content = (response.content or "").strip() or "[示例插件：无输出]"
        except Exception as e:
            logger.warning("example_plugin AI 调用失败: %s", e, exc_info=True)
            new_content = f"[示例插件：生成失败 - {e}]"

        duration = round(time.perf_counter() - t0, 4)

        # 返回 State 兼容的增量更新（遵守 MetaState 数据格式约定）
        return {
            **state,
            "content": new_content,
            "analysis": state.get("analysis", ""),
            "evaluation": state.get("evaluation", {}),
            "need_revision": state.get("need_revision", False),
            "stage_durations": {**(state.get("stage_durations") or {}), "example_plugin": duration},
            "analyze_cache_hit": state.get("analyze_cache_hit", False),
            "used_tags": effective_tags,
        }

    workflow = StateGraph(dict)
    workflow.add_node("example", _example_node)
    workflow.set_entry_point("example")
    workflow.add_edge("example", END)
    return workflow.compile()

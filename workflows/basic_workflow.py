from __future__ import annotations

import json
import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from models.request import ContentRequest
from domain.memory import MemoryService
from services.ai_service import SimpleAIService
from workflows.evaluation_node import create_evaluation_node

logger = logging.getLogger(__name__)


class State(TypedDict):
    """
    工作流状态定义 - 使用 TypedDict 确保类型安全。
    """
    user_input: str
    analysis: str
    content: str
    session_id: str
    user_id: str
    evaluation: dict
    need_revision: bool
    stage_durations: dict  # 各阶段耗时（秒），如 {"analyze": 0.5, "generate": 1.2, ...}
    analyze_cache_hit: bool  # 分析阶段是否命中缓存
    used_tags: list  # 本次实际传给模型的标签（请求输入覆盖或系统历史生成，供响应返回）


def create_workflow(ai_service: SimpleAIService | None = None) -> Any:
    """
    创建工作流图。可注入 ai_service（如带缓存的实例），否则使用新建的 SimpleAIService()。
    节点会记录各阶段耗时（stage_durations）及分析阶段是否命中缓存（analyze_cache_hit）。
    """
    ai_svc = ai_service or SimpleAIService()
    memory_svc = MemoryService()

    async def _analyze_node(state: State) -> State:
        t0 = time.perf_counter()
        user_id = state.get("user_id") or ""
        try:
            data = json.loads(state["user_input"])
            request = ContentRequest(**data)
        except (json.JSONDecodeError, TypeError):
            request = ContentRequest(
                user_id=user_id,
                brand_name="",
                product_desc=state.get("user_input", ""),
                topic="",
            )
        tags_override = list(request.tags) if (getattr(request, "tags", None) and len(request.tags) > 0) else None
        try:
            memory = await memory_svc.get_memory_for_analyze(
                user_id=user_id,
                brand_name=request.brand_name or "",
                product_desc=request.product_desc or "",
                topic=request.topic or "",
                tags_override=tags_override,
            )
            preference_context = memory.get("preference_context", "") or None
            context_fingerprint = memory.get("context_fingerprint") or {"tags": [], "recent_topics": []}
            effective_tags = memory.get("effective_tags") or []
        except Exception as e:
            logger.warning("analyze_node MemoryService 查询失败，降级为空上下文: %s", e, exc_info=True)
            preference_context = None
            context_fingerprint = {"tags": sorted(str(t) for t in (tags_override or [])), "recent_topics": []}
            effective_tags = tags_override or []
        analysis_result, cache_hit = await ai_svc.analyze(
            request,
            preference_context=preference_context or None,
            context_fingerprint=context_fingerprint,
        )
        duration = round(time.perf_counter() - t0, 4)
        return {
            **state,
            "analysis": analysis_result,
            "evaluation": state.get("evaluation", {}),
            "need_revision": state.get("need_revision", False),
            "stage_durations": {**state.get("stage_durations", {}), "analyze": duration},
            "analyze_cache_hit": cache_hit,
            "used_tags": effective_tags,
        }

    async def _generate_node(state: State) -> State:
        t0 = time.perf_counter()
        topic, raw_query, doc_ctx = "", "", ""
        try:
            ui = state.get("user_input", "")
            data = json.loads(ui) if isinstance(ui, str) else {}
            if isinstance(data, dict):
                topic = str(data.get("topic", "") or "")
                raw_query = str(data.get("raw_query", "") or "")
                doc_ctx = str(data.get("session_document_context", "") or "")
        except (json.JSONDecodeError, TypeError):
            pass
        generated_content = await ai_svc.generate(
            state["analysis"],
            topic=topic,
            raw_query=raw_query,
            session_document_context=doc_ctx,
        )
        duration = round(time.perf_counter() - t0, 4)
        return {
            **state,
            "content": generated_content,
            "evaluation": state.get("evaluation", {}),
            "need_revision": state.get("need_revision", False),
            "stage_durations": {**state.get("stage_durations", {}), "generate": duration},
            "analyze_cache_hit": state.get("analyze_cache_hit", False),
            "used_tags": state.get("used_tags", []),
        }

    def _format_node(state: State) -> State:
        t0 = time.perf_counter()
        analysis = state.get("analysis")
        if isinstance(analysis, dict):
            analysis_display = (
                f"得分 {analysis.get('semantic_score', 0)}；"
                f"切入点：{analysis.get('angle', '')}；理由：{analysis.get('reason', '')}"
            )
        else:
            analysis_display = analysis if isinstance(analysis, str) else ""
        formatted_content = f"📝 推广文案：\n\n{state['content']}\n\n✨ 基于分析：{analysis_display}"
        duration = round(time.perf_counter() - t0, 4)
        return {
            **state,
            "content": formatted_content,
            "evaluation": state.get("evaluation", {}),
            "need_revision": state.get("need_revision", False),
            "stage_durations": {**state.get("stage_durations", {}), "format": duration},
            "analyze_cache_hit": state.get("analyze_cache_hit", False),
            "used_tags": state.get("used_tags", []),
        }

    workflow = StateGraph(State)
    workflow.add_node("analyze", _analyze_node)
    workflow.add_node("generate", _generate_node)
    workflow.add_node("format", _format_node)
    workflow.add_node("evaluate", create_evaluation_node(ai_svc))
    workflow.set_entry_point("analyze")
    workflow.add_edge("analyze", "generate")
    workflow.add_edge("generate", "format")
    workflow.add_edge("format", "evaluate")
    workflow.add_edge("evaluate", END)
    return workflow.compile()
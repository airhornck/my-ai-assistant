"""
分析脑子图：LangGraph 子图，供主图「编排层」按步骤调用。
内部按 analysis_plugins 调用插件中心，输出 analysis、analyze_cache_hit。
新增分析能力以插件方式在插件中心注册，子图仅负责调度与合并。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from models.request import ContentRequest
from workflows.types import MetaState

logger = logging.getLogger(__name__)


def build_analysis_brain_subgraph(ai_svc: Any) -> Any:
    """
    构建分析脑子图。状态与 MetaState 兼容（子集），入参为父图 state，返回合并后的更新。
    """
    from langgraph.graph import END, StateGraph

    async def run_analysis(state: dict) -> dict:
        base = _ensure(state)
        user_input_str = base.get("user_input") or ""
        user_id = base.get("user_id") or ""
        try:
            user_data = json.loads(user_input_str) if isinstance(user_input_str, str) else {}
        except (TypeError, json.JSONDecodeError):
            user_data = {}
        brand = user_data.get("brand_name", "")
        product = user_data.get("product_desc", "")
        topic = user_data.get("topic", "")
        tags = user_data.get("tags", [])
        preference_ctx = base.get("memory_context") or None
        if base.get("search_context"):
            preference_ctx = (preference_ctx or "") + "\n\n【网络检索信息】\n" + (base.get("search_context") or "")
        if base.get("kb_context"):
            preference_ctx = (preference_ctx or "") + "\n\n【知识库检索】\n" + (base.get("kb_context") or "")
        plan = base.get("plan") or []
        plan_has_generate = any((s.get("step") or "").lower() == "generate" for s in plan)
        strategy_mode = not plan_has_generate
        analysis_plugins = base.get("analysis_plugins") or []
        effective_tags = base.get("effective_tags") or []
        request = ContentRequest(
            user_id=user_id,
            brand_name=brand,
            product_desc=product,
            topic=topic,
            tags=tags,
        )
        t0 = time.perf_counter()
        analysis_result, cache_hit = await ai_svc.analyze(
            request,
            preference_context=preference_ctx,
            context_fingerprint={"tags": effective_tags, "analysis_plugins": sorted(analysis_plugins)},
            strategy_mode=strategy_mode,
            analysis_plugins=analysis_plugins,
        )
        existing = base.get("analysis") or {}
        if not isinstance(existing, dict):
            existing = {}
        merged = dict(analysis_result) if isinstance(analysis_result, dict) else {}
        for k, v in (existing or {}).items():
            if k not in merged:
                merged[k] = v
        logger.info("分析脑子图完成, cache_hit=%s, duration=%.3fs", cache_hit, time.perf_counter() - t0)
        return {
            **base,
            "analysis": merged,
            "analyze_cache_hit": cache_hit,
            "current_step": (base.get("current_step") or 0) + 1,
        }

    def _ensure(s: dict) -> dict:
        return {
            "user_input": s.get("user_input", ""),
            "user_id": s.get("user_id", ""),
            "plan": s.get("plan", []),
            "current_step": s.get("current_step", 0),
            "analysis_plugins": s.get("analysis_plugins", []),
            "memory_context": s.get("memory_context", ""),
            "search_context": s.get("search_context", ""),
            "kb_context": s.get("kb_context", ""),
            "effective_tags": s.get("effective_tags", []),
            "analysis": s.get("analysis", {}),
        }

    workflow = StateGraph(dict)
    workflow.add_node("run_analysis", run_analysis)
    workflow.set_entry_point("run_analysis")
    workflow.add_edge("run_analysis", END)
    return workflow.compile()

"""
生成脑子图：LangGraph 子图，供主图「编排层」按步骤调用。
内部按 generation_plugins 调用插件中心，输出 content。
新增生成能力（文本/图片/视频/PPT 等）以插件方式在插件中心注册，子图仅负责调度。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from workflows.types import MetaState

logger = logging.getLogger(__name__)


def build_generation_brain_subgraph(ai_svc: Any) -> Any:
    """
    构建生成脑子图。状态与 MetaState 兼容（子集），入参为父图 state，返回合并后的更新。
    """
    from langgraph.graph import END, StateGraph

    async def run_generate(state: dict) -> dict:
        base = _ensure(state)
        user_input_str = base.get("user_input") or ""
        try:
            user_data = json.loads(user_input_str) if isinstance(user_input_str, str) else {}
        except (TypeError, json.JSONDecodeError):
            user_data = {}
        topic = user_data.get("topic", "") or ""
        raw_query = user_data.get("raw_query", "") or ""
        doc_context = user_data.get("session_document_context", "") or ""
        analysis = base.get("analysis") or {}
        if not isinstance(analysis, dict):
            analysis = {}
        analysis_for_generate = dict(analysis)
        analysis_for_generate.setdefault("brand_name", user_data.get("brand_name", ""))
        analysis_for_generate.setdefault("product_desc", user_data.get("product_desc", ""))
        memory_ctx = base.get("memory_context") or ""
        generation_plugins = base.get("generation_plugins") or []
        platform = base.get("_generate_platform", "")  # 可选，由主图在调用前写入
        output_type = base.get("_generate_output_type", "text")
        if platform:
            topic = f"{topic} {platform}".strip()
        source_content = (base.get("content") or "").strip() if output_type == "rewrite" else None
        generated = await ai_svc.generate(
            analysis_for_generate,
            topic=topic,
            raw_query=raw_query,
            session_document_context=doc_context,
            output_type=output_type,
            generation_plugins=generation_plugins,
            memory_context=memory_ctx,
            source_content=source_content if (output_type == "rewrite" and source_content) else None,
        )
        logger.info("生成脑子图完成, content_length=%s", len(generated or ""))
        return {
            **base,
            "content": generated or "",
            "current_step": (base.get("current_step") or 0) + 1,
        }

    def _ensure(s: dict) -> dict:
        return {
            "user_input": s.get("user_input", ""),
            "analysis": s.get("analysis", {}),
            "content": s.get("content", ""),
            "memory_context": s.get("memory_context", ""),
            "current_step": s.get("current_step", 0),
            "generation_plugins": s.get("generation_plugins", []),
            "_generate_platform": s.get("_generate_platform", ""),
            "_generate_output_type": s.get("_generate_output_type", "text"),
        }

    workflow = StateGraph(dict)
    workflow.add_node("run_generate", run_generate)
    workflow.set_entry_point("run_generate")
    workflow.add_edge("run_generate", END)
    return workflow.compile()

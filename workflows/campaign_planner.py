"""
活动策划工作流（原 strategy_workflow）：生成系统性营销活动方案。
作为可选执行单元，可被 orchestration_node 调用或独立使用。
若注入 knowledge_port / case_service / methodology_service，则委托 strategy_orchestrator 做意图与画像匹配的并行拉取。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from services.ai_service import SimpleAIService
from domain.memory import MemoryService
from services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


async def run_campaign_planner(
    user_input: str,
    user_id: str,
    session_id: str,
    ai_service: SimpleAIService | None = None,
    memory_service: MemoryService | None = None,
    retrieval_service: RetrievalService | None = None,
    knowledge_port: Any = None,
    case_service: Any = None,
    methodology_service: Any = None,
) -> dict[str, Any]:
    """
    活动策划：检索行业知识 + 用户记忆 → 生成营销活动方案。
    若提供 knowledge_port / case_service / methodology_service，则走 strategy_orchestrator（方法论+知识库+案例并行）。
    """
    if knowledge_port is not None or case_service is not None or methodology_service is not None:
        from workflows.strategy_orchestrator import run_campaign_with_context
        return await run_campaign_with_context(
            user_input,
            user_id,
            session_id,
            ai_service=ai_service,
            memory_service=memory_service,
            knowledge_port=knowledge_port,
            case_service=case_service,
            methodology_service=methodology_service,
        )

    ai_svc = ai_service or SimpleAIService()
    mem_svc = memory_service or MemoryService()
    retr_svc = retrieval_service or RetrievalService()

    try:
        data = json.loads(user_input) if isinstance(user_input, str) else {}
    except (TypeError, json.JSONDecodeError):
        data = {}
    brand = data.get("brand_name", "")
    product = data.get("product_desc", "")
    topic = data.get("topic", "")

    from langchain_core.messages import HumanMessage, SystemMessage

    query = f"{brand} {topic} {product}".strip() or "营销策略 内容日历"
    knowledge_passages = await retr_svc.retrieve(query, top_k=4)
    knowledge_text = "\n\n".join(knowledge_passages) if knowledge_passages else "（暂无相关知识库内容）"

    tags_override = list(data["tags"]) if isinstance(data.get("tags"), list) and data.get("tags") else None
    memory = await mem_svc.get_memory_for_analyze(
        user_id=user_id,
        brand_name=brand,
        product_desc=product,
        topic=topic,
        tags_override=tags_override,
    )
    user_memory = memory.get("preference_context", "") or "（暂无用户记忆）"

    system_prompt = (
        "你是营销活动策划专家。根据「行业知识」「用户记忆」和「本次请求」，"
        "生成一份完整的营销活动方案（内容日历、投放计划、预算分配等）。"
    )
    user_prompt = f"""【本次请求】
品牌：{brand}
产品：{product}
目标：{topic}

【行业知识】
{knowledge_text}

【用户记忆】
{user_memory}

请输出营销活动方案（Markdown 格式）。"""

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    router = await ai_svc.router.route(task_type="generation", prompt_complexity="high")
    response = await router.ainvoke(messages)
    campaign_plan = (response.content or "").strip()

    return {
        "user_input": user_input,
        "user_id": user_id,
        "session_id": session_id,
        "analysis": {"campaign_planner": True},
        "content": campaign_plan,
        "evaluation": {},
        "need_revision": False,
        "stage_durations": {},
        "analyze_cache_hit": False,
        "used_tags": memory.get("effective_tags", []),
    }

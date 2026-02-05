"""
活动策略编排：按用户意图与画像，并行拉取营销方法论、知识库、营销策略案例模板，
合并后注入 prompt，保障性能与体验（并行、超时降级、缓存复用）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from services.ai_service import SimpleAIService
from domain.memory import MemoryService

logger = logging.getLogger(__name__)

# 单路超时（秒），避免某路拖死整体
RETRIEVAL_TIMEOUT = 12
MAX_KNOWLEDGE_PASSAGES = 4
MAX_CASE_PASSAGES = 2
MAX_METHODOLOGY_PASSAGES = 2


async def _retrieve_with_timeout(coro, fallback: List[str]) -> List[str]:
    """执行检索协程，超时则返回 fallback。"""
    try:
        return await asyncio.wait_for(coro, timeout=RETRIEVAL_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("检索超时，使用空结果")
        return fallback
    except Exception as e:
        logger.warning("检索异常: %s", e)
        return fallback


async def run_campaign_with_context(
    user_input: str,
    user_id: str,
    session_id: str,
    *,
    ai_service: SimpleAIService | None = None,
    memory_service: MemoryService | None = None,
    knowledge_port: Any = None,
    case_service: Any = None,
    methodology_service: Any = None,
) -> dict[str, Any]:
    """
    活动策划编排：意图+画像 → 并行拉取 方法论 / 知识库 / 案例模板 → 合并注入 → 生成方案。
    任一依赖未注入时仅用已有能力（如仅知识库），不阻塞。
    """
    ai_svc = ai_service or SimpleAIService()
    mem_svc = memory_service or MemoryService()

    try:
        data = json.loads(user_input) if isinstance(user_input, str) else {}
    except (TypeError, json.JSONDecodeError):
        data = {}
    brand = data.get("brand_name", "")
    product = data.get("product_desc", "")
    topic = data.get("topic", "")
    tags_override = list(data["tags"]) if isinstance(data.get("tags"), list) and data.get("tags") else None

    query = f"{brand} {topic} {product}".strip() or "营销策略 内容日历"
    industry = data.get("industry") or ""
    goal_type = data.get("goal_type") or topic or ""

    # 并行拉取：知识库 / 案例 / 方法论（可选）
    knowledge_passages: List[str] = []
    case_passages: List[str] = []
    methodology_passages: List[str] = []

    async def get_knowledge() -> List[str]:
        if knowledge_port is None:
            return []
        return await knowledge_port.retrieve(query, top_k=MAX_KNOWLEDGE_PASSAGES)

    async def get_cases() -> List[str]:
        if case_service is None:
            return []
        try:
            result = await case_service.list_cases(
                industry=industry or None,
                goal_type=goal_type or None,
                order_by_score=True,
                page=1,
                page_size=MAX_CASE_PASSAGES,
                include_content=True,
            )
            items = result.get("items") or []
            out = []
            for x in items:
                title = x.get("title", "")
                content = x.get("content") or x.get("summary") or ""
                out.append(f"【案例】{title}\n{content[:1200]}" if content else f"【案例】{title}")
            return out
        except Exception as e:
            logger.warning("get_cases 异常: %s", e)
            return []

    async def get_methodology() -> List[str]:
        if methodology_service is None:
            return []
        try:
            docs = methodology_service.list_docs()
            out = []
            for d in docs[:MAX_METHODOLOGY_PASSAGES]:
                path = d.get("path") or d.get("name", "") + ".md"
                content = methodology_service.get_content(path)
                if content:
                    out.append(content[:800])
            return out
        except Exception as e:
            logger.warning("get_methodology 异常: %s", e)
            return []

    # 并行拉取：知识库 / 案例 / 方法论
    task_names: List[str] = []
    coros: List[Any] = []
    if knowledge_port is not None:
        task_names.append("knowledge")
        coros.append(_retrieve_with_timeout(get_knowledge(), []))
    if case_service is not None:
        task_names.append("case")
        coros.append(_retrieve_with_timeout(get_cases(), []))
    if methodology_service is not None:
        task_names.append("methodology")
        coros.append(_retrieve_with_timeout(get_methodology(), []))
    if coros:
        results = await asyncio.gather(*coros, return_exceptions=True)
        for name, r in zip(task_names, results):
            val = r if not isinstance(r, Exception) else []
            if isinstance(r, Exception):
                logger.warning("并行拉取 %s 异常: %s", name, r)
            if name == "knowledge":
                knowledge_passages = val
            elif name == "case":
                case_passages = val
            else:
                methodology_passages = val

    # 若无知识库 port 则回退到原有 retrieval_service（兼容旧调用方）
    if not knowledge_passages and knowledge_port is None:
        try:
            from services.retrieval_service import RetrievalService
            retr = RetrievalService()
            knowledge_passages = await _retrieve_with_timeout(
                retr.retrieve(query, top_k=MAX_KNOWLEDGE_PASSAGES),
                [],
            )
        except Exception as e:
            logger.warning("回退 RetrievalService 失败: %s", e)

    knowledge_text = "\n\n".join(knowledge_passages) if knowledge_passages else "（暂无相关知识库内容）"
    if methodology_passages:
        knowledge_text = "【营销方法论】\n\n" + "\n\n".join(methodology_passages) + "\n\n【行业知识】\n\n" + knowledge_text
    if case_passages:
        knowledge_text = knowledge_text + "\n\n【参考案例】\n\n" + "\n\n".join(case_passages)

    memory = await mem_svc.get_memory_for_analyze(
        user_id=user_id,
        brand_name=brand,
        product_desc=product,
        topic=topic,
        tags_override=tags_override,
    )
    user_memory = memory.get("preference_context", "") or "（暂无用户记忆）"

    system_prompt = (
        "你是营销活动策划专家。根据「行业知识」「用户记忆」和「本次请求」生成营销活动方案。"
        "若下方有【参考案例】，请优先参考其结构与要点，结合本次请求进行改写或填空，形成贴合客户需求的方案（内容日历、投放计划、预算分配等）。"
    )
    user_prompt = f"""【本次请求】
品牌：{brand}
产品：{product}
目标：{topic}

【行业知识】
{knowledge_text}

【用户记忆】
{user_memory}

请输出营销活动方案（Markdown 格式）。若上方有参考案例，请以其为基础改写或填空，避免从零堆砌。"""

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

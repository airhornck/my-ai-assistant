from __future__ import annotations

import json
import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import select

from database import AsyncSessionLocal, InteractionHistory, UserProfile
from models.request import ContentRequest
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


def _build_preference_context(
    profile: UserProfile | None, histories: list, tags_override: list | None = None
) -> str:
    """
    从 UserProfile 与最近 InteractionHistory 构建 preference_context 文本。
    tags_override：若提供则用其作为兴趣标签（请求输入覆盖）；否则用 profile.tags（系统历史生成）。
    """
    parts = []
    if profile:
        if profile.preferred_style:
            parts.append(f"偏好风格：{profile.preferred_style}")
        if profile.industry:
            parts.append(f"行业：{profile.industry}")
        if profile.brand_name:
            parts.append(f"品牌：{profile.brand_name}")
        # 兴趣标签：请求输入覆盖 > 系统根据历史生成的 profile.tags
        tags_to_show = tags_override if (tags_override is not None and len(tags_override) > 0) else (profile.tags if profile.tags and isinstance(profile.tags, list) else [])
        if tags_to_show:
            tags_str = "、".join(str(t) for t in tags_to_show)
            parts.append(f"兴趣标签：{tags_str}")
    if parts:
        parts.insert(0, "【用户画像】")
        parts.append("")

    if histories:
        parts.append("【近期交互摘要】")
        for i, h in enumerate(histories, 1):
            topic = ""
            if h.user_input:
                try:
                    data = json.loads(h.user_input)
                    topic = (data.get("topic") or "") if isinstance(data, dict) else ""
                except (json.JSONDecodeError, TypeError):
                    pass
            summary = (h.ai_output or "")[:120].strip()
            if summary and len((h.ai_output or "")) > 120:
                summary += "…"
            line = f"  {i}. 主题：{topic or '—'}"
            if summary:
                line += f"；输出摘要：{summary}"
            parts.append(line)
        parts.append("")

    return "\n".join(parts).strip() if parts else ""


def _build_context_fingerprint(
    profile: UserProfile | None, histories: list, tags_override: list | None = None
) -> dict:
    """
    构建用于分析缓存的上下文指纹：用户长期标签（参与缓存键）+ 近三次交互主题（供扩展）。
    tags_override：若提供则用其作为缓存键中的 tags；否则用 profile.tags。
    """
    if tags_override is not None and len(tags_override) > 0:
        tags_sorted = sorted(str(t) for t in tags_override)
    else:
        tags_sorted = []
        if profile and getattr(profile, "tags", None) and isinstance(profile.tags, list):
            tags_sorted = sorted(str(t) for t in profile.tags)
    recent_topics = []
    for h in histories[:3]:
        topic = ""
        if getattr(h, "user_input", None):
            try:
                data = json.loads(h.user_input) if isinstance(h.user_input, str) else {}
                topic = (data.get("topic") or "").strip() if isinstance(data, dict) else ""
            except (json.JSONDecodeError, TypeError):
                pass
        if topic:
            recent_topics.append(topic)
    # 去重并排序，使 (A,B,A) 与 (A,B) 在集合上一致，便于命中
    recent_topics_sorted = sorted(set(recent_topics))
    return {"tags": tags_sorted, "recent_topics": recent_topics_sorted}


def create_workflow(ai_service: SimpleAIService | None = None) -> Any:
    """
    创建工作流图。可注入 ai_service（如带缓存的实例），否则使用新建的 SimpleAIService()。
    节点会记录各阶段耗时（stage_durations）及分析阶段是否命中缓存（analyze_cache_hit）。
    """
    ai_svc = ai_service or SimpleAIService()

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
        preference_context = ""
        context_fingerprint = {"tags": [], "recent_topics": []}
        # 先按请求输入确定 effective_tags，保证缓存键与请求一致（即使 DB 异常也能命中）
        if getattr(request, "tags", None) and len(request.tags) > 0:
            effective_tags = list(request.tags)
        else:
            effective_tags = []
        async with AsyncSessionLocal() as session:
            try:
                rp = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
                profile = rp.scalar_one_or_none()
                rh = await session.execute(
                    select(InteractionHistory)
                    .where(InteractionHistory.user_id == user_id)
                    .order_by(InteractionHistory.created_at.desc())
                    .limit(3)
                )
                histories = rh.scalars().all()
                # 无请求 tags 时再用系统根据历史生成的 profile.tags
                if not effective_tags and profile and getattr(profile, "tags", None) and isinstance(profile.tags, list):
                    effective_tags = list(profile.tags)
                preference_context = _build_preference_context(profile, histories, tags_override=effective_tags)
                context_fingerprint = _build_context_fingerprint(profile, histories, tags_override=effective_tags)
            except Exception as e:
                logger.warning("analyze_node 查询长期记忆失败，降级为空上下文: %s", e, exc_info=True)
                # 异常时 context_fingerprint 仍用上面已算好的 effective_tags，保证缓存键一致
                context_fingerprint = {"tags": sorted(str(t) for t in effective_tags), "recent_topics": []}
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
        generated_content = await ai_svc.generate(state["analysis"])
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
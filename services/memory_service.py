"""
记忆服务：用户记忆的唯一样式（与 LangGraph Checkpoint 分工明确）。

- **本服务**：长期与业务记忆
  - 第一层：品牌事实库、成功案例库（UserProfile）
  - 第二层：用户画像（tags, industry, brand_name 等）
  - 第三层：近期交互（InteractionHistory，跨会话）
- **LangGraph Checkpoint**：单次对话内的图状态（step_outputs、plan 等），由 thread_id 持久化

在 meta_workflow 中，memory_query 步骤调用 get_memory_for_analyze，结果写入 memory_context。
可选 SmartCache 以请求指纹缓存；用户画像更新频繁时建议更短 TTL 或写后失效。
"""
from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from sqlalchemy import select

from database import AsyncSessionLocal, InteractionHistory, UserProfile

if TYPE_CHECKING:
    from cache.smart_cache import SmartCache

logger = logging.getLogger(__name__)


class MemoryService:
    """
    封装对用户三层记忆的查询，供工作流构建提示词使用。
    优先使用品牌事实和成功案例构建上下文。可选注入 SmartCache 缓存 get_memory_for_analyze 结果。
    """

    def __init__(self, cache: "SmartCache | None" = None) -> None:
        self._cache = cache

    async def get_recent_conversation_text(
        self, user_id: str, session_id: str = "", limit: int = 5
    ) -> str:
        """获取近期对话文本，用于多轮上下文。session_id 非空时优先取同会话记录。格式：用户：xxx\n助手：yyy\n..."""
        if not (user_id or "").strip():
            return ""
        async with AsyncSessionLocal() as session:
            try:
                q = (
                    select(InteractionHistory)
                    .where(InteractionHistory.user_id == user_id)
                    .order_by(InteractionHistory.created_at.desc())
                    .limit(limit * 2)
                )
                rh = await session.execute(q)
                rows = list(rh.scalars().all())
                # 同会话优先：若指定 session_id，优先选取该会话记录
                if session_id and rows:
                    same = [r for r in rows if getattr(r, "session_id", None) == session_id]
                    rows = same[:limit] if same else rows[:limit]
                else:
                    rows = rows[:limit]
                rows.reverse()  # chronological order
                parts = []
                for h in rows:
                    raw_val = ""
                    if getattr(h, "user_input", None):
                        try:
                            data = json.loads(h.user_input) if isinstance(h.user_input, str) else {}
                            raw_val = (data.get("raw_query") or data.get("message") or "").strip()
                        except (json.JSONDecodeError, TypeError):
                            raw_val = (h.user_input or "")[:200]
                    if raw_val:
                        parts.append(f"用户：{raw_val[:300]}")
                    out = (getattr(h, "ai_output", None) or "").strip()[:300]
                    if out:
                        parts.append(f"助手：{out}")
                return "\n".join(parts) if parts else ""
            except Exception as e:
                logger.warning("get_recent_conversation_text 失败: %s", e)
                return ""

    async def get_user_summary(self, user_id: str) -> str:
        """获取用户简短摘要（品牌、行业等），用于闲聊中回答「我是谁」类问题。"""
        if not (user_id or "").strip():
            return ""
        async with AsyncSessionLocal() as session:
            try:
                r = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
                profile = r.scalar_one_or_none()
                if not profile:
                    return ""
                parts = []
                if profile.brand_name:
                    parts.append(f"品牌：{profile.brand_name}")
                if profile.industry:
                    parts.append(f"行业：{profile.industry}")
                if getattr(profile, "preferred_style", None):
                    parts.append(f"偏好风格：{profile.preferred_style}")
                return "；".join(parts) if parts else ""
            except Exception as e:
                logger.warning("get_user_summary 失败: %s", e)
                return ""

    async def query_brand_facts(self, user_id: str, topic: str) -> str:
        """
        查询用户的品牌事实库，返回与 topic 相关的格式化文本。
        brand_facts 格式示例：[{"fact": "...", "category": "..."}]
        """
        async with AsyncSessionLocal() as session:
            try:
                r = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
                profile = r.scalar_one_or_none()
                if not profile or not getattr(profile, "brand_facts", None):
                    return ""
                facts = profile.brand_facts
                if not isinstance(facts, list):
                    return ""
                lines = []
                for item in facts:
                    if isinstance(item, dict):
                        fact = item.get("fact") or item.get("content") or str(item)
                    else:
                        fact = str(item)
                    if fact:
                        lines.append(f"  - {fact}")
                return "\n".join(lines).strip() if lines else ""
            except Exception as e:
                logger.warning("query_brand_facts 失败: %s", e, exc_info=True)
                return ""

    async def query_success_cases(self, user_id: str, topic: str) -> str:
        """
        查询用户的成功案例库，返回与 topic 相关的格式化文本。
        success_cases 格式示例：[{"title": "...", "description": "...", "outcome": "..."}]
        """
        async with AsyncSessionLocal() as session:
            try:
                r = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
                profile = r.scalar_one_or_none()
                if not profile or not getattr(profile, "success_cases", None):
                    return ""
                cases = profile.success_cases
                if not isinstance(cases, list):
                    return ""
                lines = []
                for i, item in enumerate(cases[:5], 1):
                    if not isinstance(item, dict):
                        continue
                    title = item.get("title") or item.get("name") or f"案例{i}"
                    desc = item.get("description") or item.get("desc") or ""
                    outcome = item.get("outcome") or ""
                    parts = [f"  {i}. {title}"]
                    if desc:
                        parts.append(f"     描述：{desc[:200]}{'…' if len(str(desc)) > 200 else ''}")
                    if outcome:
                        parts.append(f"     效果：{outcome[:150]}{'…' if len(str(outcome)) > 150 else ''}")
                    lines.append("\n".join(parts))
                return "\n\n".join(lines).strip() if lines else ""
            except Exception as e:
                logger.warning("query_success_cases 失败: %s", e, exc_info=True)
                return ""

    async def get_memory_for_analyze(
        self,
        user_id: str,
        brand_name: str,
        product_desc: str,
        topic: str,
        tags_override: list | None = None,
    ) -> dict[str, Any]:
        """
        获取用于分析节点的完整记忆上下文。
        优先使用品牌事实与成功案例，再叠加用户画像与近期交互。
        若注入 SmartCache，则按请求指纹（user_id + brand + product + topic + tags）缓存，TTL 见 TTL_MEMORY；
        用户画像更新后可能陈旧，可设更短 TTL（TTL_PROFILE）或写后手动使缓存失效。
        """
        if self._cache is not None:
            from cache.smart_cache import build_fingerprint_key, TTL_MEMORY
            key = build_fingerprint_key("memory:", {
                "user_id": (user_id or "").strip(),
                "brand_name": (brand_name or "").strip(),
                "product_desc": (product_desc or "").strip(),
                "topic": (topic or "").strip(),
                "tags": sorted(str(t) for t in (tags_override or [])),
            })
            result, hit = await self._cache.get_or_set(
                key,
                lambda: self._get_memory_for_analyze_impl(user_id, brand_name, product_desc, topic, tags_override),
                ttl=TTL_MEMORY,
            )
            if hit:
                logger.debug("get_memory_for_analyze 缓存命中 key=%s", key)
            return result
        return await self._get_memory_for_analyze_impl(user_id, brand_name, product_desc, topic, tags_override)

    async def _get_memory_for_analyze_impl(
        self,
        user_id: str,
        brand_name: str,
        product_desc: str,
        topic: str,
        tags_override: list | None = None,
    ) -> dict[str, Any]:
        """实际查询逻辑，供 get_memory_for_analyze 或缓存未命中时调用。"""
        effective_tags = list(tags_override) if (tags_override and len(tags_override) > 0) else []
        context_fingerprint = {"tags": [], "recent_topics": []}
        parts = []

        async with AsyncSessionLocal() as session:
            try:
                rp = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
                profile = rp.scalar_one_or_none()

                if profile:
                    if not effective_tags and getattr(profile, "tags", None) and isinstance(profile.tags, list):
                        effective_tags = list(profile.tags)
                    context_fingerprint["tags"] = sorted(str(t) for t in effective_tags)

                    # 第一层：品牌事实库（优先）
                    brand_facts_text = self._get_brand_facts_from_profile(profile)
                    if brand_facts_text:
                        parts.append("【品牌事实库】")
                        parts.append(brand_facts_text)
                        parts.append("")

                    # 第一层：成功案例库（优先）
                    success_cases_text = self._get_success_cases_from_profile(profile)
                    if success_cases_text:
                        parts.append("【成功案例库】")
                        parts.append(success_cases_text)
                        parts.append("")

                    # 第二层：用户画像
                    profile_parts = []
                    if profile.preferred_style:
                        profile_parts.append(f"偏好风格：{profile.preferred_style}")
                    if profile.industry:
                        profile_parts.append(f"行业：{profile.industry}")
                    if profile.brand_name:
                        profile_parts.append(f"品牌：{profile.brand_name}")
                    tags_to_show = effective_tags if effective_tags else (profile.tags if isinstance(getattr(profile, "tags", None), list) else [])
                    if tags_to_show:
                        profile_parts.append("兴趣标签：" + "、".join(str(t) for t in tags_to_show))
                    if profile_parts:
                        parts.append("【用户画像】")
                        parts.extend(profile_parts)
                        parts.append("")

                # 第三层：近期交互（P1: 扩至 5 条、 richer 摘要，便于在 prompt 中更突出）
                rh = await session.execute(
                    select(InteractionHistory)
                    .where(InteractionHistory.user_id == user_id)
                    .order_by(InteractionHistory.created_at.desc())
                    .limit(5)
                )
                histories = rh.scalars().all()
                recent_topics = []
                if histories:
                    parts.append("【近期交互（重要：用于延续用户偏好与主题，请优先参考）】")
                    for i, h in enumerate(histories, 1):
                        topic_val = brand_val = product_val = raw_val = ""
                        if getattr(h, "user_input", None):
                            try:
                                data = json.loads(h.user_input) if isinstance(h.user_input, str) else {}
                                if isinstance(data, dict):
                                    topic_val = (data.get("topic") or "").strip()
                                    brand_val = (data.get("brand_name") or "").strip()
                                    product_val = (data.get("product_desc") or "").strip()
                                    raw_val = (data.get("raw_query") or data.get("message") or "").strip()[:80]
                                if topic_val:
                                    recent_topics.append(topic_val)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        summary = (getattr(h, "ai_output", None) or "")[:150].strip()
                        if summary and len((getattr(h, "ai_output", None) or "")) > 150:
                            summary += "…"
                        segs = [f"  {i}. "]
                        if brand_val or product_val:
                            segs.append(f"品牌/产品：{brand_val or ''} {product_val or ''}；")
                        if topic_val or raw_val:
                            segs.append(f"主题/需求：{topic_val or raw_val or '—'}")
                        if summary:
                            segs.append(f"；上次输出摘要：{summary}")
                        parts.append("".join(segs).strip() or f"  {i}. —")
                    parts.append("")
                context_fingerprint["recent_topics"] = sorted(set(recent_topics))

            except Exception as e:
                logger.warning("get_memory_for_analyze 查询失败: %s", e, exc_info=True)
                if not effective_tags:
                    context_fingerprint["tags"] = []
                context_fingerprint["recent_topics"] = []

        preference_context = "\n".join(parts).strip() if parts else ""
        return {
            "preference_context": preference_context,
            "context_fingerprint": context_fingerprint,
            "effective_tags": effective_tags,
        }

    def _get_brand_facts_from_profile(self, profile: UserProfile) -> str:
        """从 profile 提取品牌事实文本。"""
        facts = getattr(profile, "brand_facts", None)
        if not isinstance(facts, list):
            return ""
        lines = []
        for item in facts:
            if isinstance(item, dict):
                fact = item.get("fact") or item.get("content") or str(item)
            else:
                fact = str(item)
            if fact:
                lines.append(f"  - {fact}")
        return "\n".join(lines).strip() if lines else ""

    def _get_success_cases_from_profile(self, profile: UserProfile) -> str:
        """从 profile 提取成功案例文本。"""
        cases = getattr(profile, "success_cases", None)
        if not isinstance(cases, list):
            return ""
        lines = []
        for i, item in enumerate(cases[:5], 1):
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name") or f"案例{i}"
            desc = item.get("description") or item.get("desc") or ""
            outcome = item.get("outcome") or ""
            parts = [f"  {i}. {title}"]
            if desc:
                parts.append(f"     描述：{str(desc)[:200]}{'…' if len(str(desc)) > 200 else ''}")
            if outcome:
                parts.append(f"     效果：{str(outcome)[:150]}{'…' if len(str(outcome)) > 150 else ''}")
            lines.append("\n".join(parts))
        return "\n\n".join(lines).strip() if lines else ""

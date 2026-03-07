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

from database import AsyncSessionLocal, InteractionHistory, UserProfile, UserMemoryItem

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
            from cache.smart_cache import _normalize_for_key, generate_cache_key, TTL_MEMORY
            uid = (user_id or "").strip()
            req = {
                "brand_name": (brand_name or "").strip(),
                "product_desc": (product_desc or "").strip(),
                "topic": (topic or "").strip(),
                "tags": sorted(str(t) for t in (tags_override or [])),
            }
            key = "memory:" + uid + ":" + generate_cache_key({k: _normalize_for_key(v) for k, v in req.items()})
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
        """
        实际查询逻辑：短画像 + 语义 top_k 记忆条 + 近期 2～3 条交互，总 token 预算内拼装。
        返回值形态不变，供 get_memory_for_analyze 与策略脑/分析脑兼容。
        """
        MEMORY_TOP_K = 5
        RECENT_LIMIT = 3
        CONTENT_TRUNCATE_CHARS = 80
        TOKEN_BUDGET_CHARS = 1200  # 约 600 tokens 的字符近似（中文约 2 字/token）

        effective_tags = list(tags_override) if (tags_override and len(tags_override) > 0) else []
        context_fingerprint = {"tags": [], "recent_topics": []}
        parts: list[str] = []

        async with AsyncSessionLocal() as session:
            try:
                rp = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
                profile = rp.scalar_one_or_none()
                if profile:
                    if not effective_tags and getattr(profile, "tags", None) and isinstance(profile.tags, list):
                        effective_tags = list(profile.tags)
                    context_fingerprint["tags"] = sorted(str(t) for t in effective_tags)

                # 1. 短画像（1～2 行）
                profile_line_parts = []
                if profile:
                    if profile.brand_name:
                        profile_line_parts.append(f"品牌：{profile.brand_name}")
                    if profile.industry:
                        profile_line_parts.append(f"行业：{profile.industry}")
                    if getattr(profile, "preferred_style", None):
                        profile_line_parts.append(f"风格：{profile.preferred_style}")
                    tags_show = effective_tags or (getattr(profile, "tags", None) if isinstance(getattr(profile, "tags", None), list) else [])
                    if tags_show:
                        profile_line_parts.append("标签：" + "、".join(str(t) for t in tags_show[:8]))
                if profile_line_parts:
                    parts.append("【用户画像】" + "；".join(profile_line_parts))

                # 2. 语义 top_k 记忆条
                query_parts = [topic or "", product_desc or "", brand_name or ""]
                query_text = " ".join(s.strip() for s in query_parts if (s or "").strip()).strip() or "用户偏好"
                from services.memory_embedding import get_embedding
                query_embedding = get_embedding(query_text)
                if query_embedding:
                    rm = await session.execute(
                        select(UserMemoryItem).where(UserMemoryItem.user_id == user_id)
                    )
                    all_items = rm.scalars().all()
                    items_with_emb = [(r, r.embedding_json) for r in all_items if getattr(r, "embedding_json", None) and isinstance(r.embedding_json, list)]
                    if items_with_emb:
                        import numpy as np
                        query_arr = np.array(query_embedding, dtype=float)
                        scored = []
                        for row, emb in items_with_emb:
                            arr = np.array(emb, dtype=float)
                            if arr.size != query_arr.size:
                                continue
                            norm_q = np.linalg.norm(query_arr)
                            norm_a = np.linalg.norm(arr)
                            if norm_q < 1e-9 or norm_a < 1e-9:
                                continue
                            sim = float(np.dot(query_arr, arr) / (norm_q * norm_a))
                            scored.append((sim, row))
                        scored.sort(reverse=True, key=lambda x: x[0])
                        top_items = [row for _, row in scored[:MEMORY_TOP_K]]
                        if top_items:
                            mem_lines = []
                            for r in top_items:
                                c = (r.content or "").strip()
                                if len(c) > CONTENT_TRUNCATE_CHARS:
                                    c = c[:CONTENT_TRUNCATE_CHARS] + "…"
                                if c:
                                    mem_lines.append(f"  - {c}")
                            if mem_lines:
                                parts.append("【相关记忆】")
                                parts.extend(mem_lines)

                # 3. 近期 2～3 条交互
                rh = await session.execute(
                    select(InteractionHistory)
                    .where(InteractionHistory.user_id == user_id)
                    .order_by(InteractionHistory.created_at.desc())
                    .limit(RECENT_LIMIT)
                )
                histories = rh.scalars().all()
                recent_topics = []
                if histories:
                    parts.append("【近期交互】")
                    for i, h in enumerate(histories, 1):
                        topic_val = raw_val = ""
                        if getattr(h, "user_input", None):
                            try:
                                data = json.loads(h.user_input) if isinstance(h.user_input, str) else {}
                                if isinstance(data, dict):
                                    topic_val = (data.get("topic") or "").strip()
                                    raw_val = (data.get("raw_query") or data.get("message") or "").strip()[:60]
                                if topic_val:
                                    recent_topics.append(topic_val)
                            except (json.JSONDecodeError, TypeError):
                                raw_val = (str(h.user_input) or "")[:60]
                        out_short = (getattr(h, "ai_output", None) or "").strip()[:80]
                        if len((getattr(h, "ai_output", None) or "")) > 80:
                            out_short += "…"
                        line = f"  {i}. " + (topic_val or raw_val or "—")
                        if out_short:
                            line += "；" + out_short
                        parts.append(line)
                context_fingerprint["recent_topics"] = sorted(set(recent_topics))

            except Exception as e:
                logger.warning("get_memory_for_analyze 查询失败: %s", e, exc_info=True)
                if not effective_tags:
                    context_fingerprint["tags"] = []
                context_fingerprint["recent_topics"] = []

        preference_context = "\n".join(parts).strip() if parts else ""
        if len(preference_context) > TOKEN_BUDGET_CHARS:
            preference_context = preference_context[:TOKEN_BUDGET_CHARS] + "…"
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

    async def _invalidate_memory_cache_for_user_async(self, user_id: str) -> None:
        """写后使该用户所有记忆缓存失效（异步版本，在 add_memory/delete_memory 内调用）。"""
        if not (user_id or "").strip() or self._cache is None:
            return
        prefix = "memory:" + (user_id or "").strip() + ":"
        n = await self._cache.delete_by_prefix(prefix)
        if n:
            logger.debug("记忆缓存已失效 user_id=%s 共 %d 个键", user_id, n)

    async def add_memory(self, user_id: str, content: str, source: str) -> int | None:
        """写入一条记忆，计算 embedding 并落库；写后失效该用户记忆缓存。返回 memory_id，失败返回 None。"""
        if not (user_id or "").strip() or not (content or "").strip():
            return None
        from services.memory_embedding import get_embedding
        embedding = get_embedding(content.strip())
        async with AsyncSessionLocal() as session:
            try:
                item = UserMemoryItem(
                    user_id=(user_id or "").strip(),
                    content=(content or "").strip(),
                    source=(source or "explicit")[:32],
                    embedding_json=embedding if isinstance(embedding, list) else None,
                )
                session.add(item)
                await session.commit()
                await session.refresh(item)
                mid = item.id
                await self._invalidate_memory_cache_for_user_async(user_id)
                return mid
            except Exception as e:
                logger.warning("add_memory 失败: %s", e, exc_info=True)
                await session.rollback()
                return None

    async def list_memories(self, user_id: str) -> dict[str, Any]:
        """返回该用户的画像摘要 + 记忆条列表（id、content_preview、source、created_at）+ 近期交互条数。"""
        if not (user_id or "").strip():
            return {"profile_summary": {}, "memory_items": [], "recent_interaction_count": 0}
        PREVIEW_LEN = 80
        async with AsyncSessionLocal() as session:
            try:
                rp = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
                profile = rp.scalar_one_or_none()
                profile_summary = {}
                if profile:
                    if profile.brand_name:
                        profile_summary["brand_name"] = profile.brand_name
                    if profile.industry:
                        profile_summary["industry"] = profile.industry
                    if getattr(profile, "preferred_style", None):
                        profile_summary["preferred_style"] = profile.preferred_style
                    if getattr(profile, "tags", None) and isinstance(profile.tags, list):
                        profile_summary["tags"] = list(profile.tags)
                rh = await session.execute(
                    select(UserMemoryItem)
                    .where(UserMemoryItem.user_id == user_id)
                    .order_by(UserMemoryItem.created_at.desc())
                )
                rows = rh.scalars().all()
                memory_items = [
                    {
                        "id": r.id,
                        "content_preview": (r.content or "")[:PREVIEW_LEN] + ("…" if len(r.content or "") > PREVIEW_LEN else ""),
                        "source": r.source or "",
                        "created_at": r.created_at.isoformat() if r.created_at else "",
                    }
                    for r in rows
                ]
                rc = await session.execute(
                    select(InteractionHistory).where(InteractionHistory.user_id == user_id)
                )
                recent_count = len(rc.scalars().all())
                return {
                    "profile_summary": profile_summary,
                    "memory_items": memory_items,
                    "recent_interaction_count": recent_count,
                }
            except Exception as e:
                logger.warning("list_memories 失败: %s", e, exc_info=True)
                return {"profile_summary": {}, "memory_items": [], "recent_interaction_count": 0}

    async def get_memory_content(self, user_id: str, memory_id: int) -> dict[str, Any] | None:
        """按 id 查询单条，校验 user_id 归属后返回完整 content、source、created_at；否则返回 None。"""
        if not (user_id or "").strip():
            return None
        async with AsyncSessionLocal() as session:
            try:
                r = await session.execute(
                    select(UserMemoryItem).where(
                        UserMemoryItem.id == memory_id,
                        UserMemoryItem.user_id == user_id,
                    )
                )
                row = r.scalar_one_or_none()
                if not row:
                    return None
                return {
                    "id": row.id,
                    "user_id": row.user_id,
                    "content": row.content or "",
                    "source": row.source or "",
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
            except Exception as e:
                logger.warning("get_memory_content 失败: %s", e, exc_info=True)
                return None

    async def delete_memory(self, user_id: str, memory_id: int | None) -> bool:
        """memory_id 为 None 时删除该用户全部记忆条；否则删除指定 id（校验归属）。写后缓存失效。"""
        if not (user_id or "").strip():
            return False
        async with AsyncSessionLocal() as session:
            try:
                if memory_id is None:
                    r = await session.execute(select(UserMemoryItem).where(UserMemoryItem.user_id == user_id))
                    for row in r.scalars().all():
                        await session.delete(row)
                else:
                    r = await session.execute(
                        select(UserMemoryItem).where(
                            UserMemoryItem.id == memory_id,
                            UserMemoryItem.user_id == user_id,
                        )
                    )
                    row = r.scalar_one_or_none()
                    if not row:
                        await session.rollback()
                        return False
                    await session.delete(row)
                await session.commit()
                await self._invalidate_memory_cache_for_user_async(user_id)
                return True
            except Exception as e:
                logger.warning("delete_memory 失败: %s", e, exc_info=True)
                await session.rollback()
                return False

    async def clear_memories(self, user_id: str) -> bool:
        """清空该用户所有记忆条。等同于 delete_memory(user_id, None)。"""
        return await self.delete_memory(user_id, None)

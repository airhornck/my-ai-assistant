"""
记忆系统优化 - 步骤3/4 测试：MemoryService CRUD 与写后缓存失效。
- list_memories / get_memory_content / add_memory / delete_memory / clear_memories
- 需 DATABASE_URL；可选 REDIS_URL 测缓存失效。
"""
from __future__ import annotations

import pytest

try:
    from scripts.conftest import requires_integration
except ImportError:
    from conftest import requires_integration


@requires_integration
@pytest.mark.asyncio
async def test_list_memories_structure() -> None:
    """list_memories 返回结构含 profile_summary、memory_items、recent_interaction_count。"""
    from domain.memory import MemoryService
    svc = MemoryService()
    out = await svc.list_memories("test_crud_user_xyz")
    assert "profile_summary" in out
    assert "memory_items" in out
    assert "recent_interaction_count" in out
    assert isinstance(out["memory_items"], list)


@requires_integration
@pytest.mark.asyncio
async def test_add_memory_and_list_and_get_and_delete() -> None:
    """add_memory → list 可见 → get_memory_content 完整内容 → delete_memory 删除。"""
    from domain.memory import MemoryService
    from database import UserProfile, AsyncSessionLocal
    from sqlalchemy import select
    uid = "test_crud_user_xyz"
    svc = MemoryService()
    # 确保有 user_profile（外键）
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(UserProfile).where(UserProfile.user_id == uid))
        if r.scalar_one_or_none() is None:
            session.add(UserProfile(user_id=uid))
            await session.commit()
    # 添加
    mid = await svc.add_memory(uid, "测试记忆内容：品牌A，行业电商", "explicit")
    assert mid is not None
    # 列表应有
    out = await svc.list_memories(uid)
    assert len(out["memory_items"]) >= 1
    one = next((m for m in out["memory_items"] if m["id"] == mid), None)
    assert one is not None
    assert "品牌A" in (one.get("content_preview") or "")
    # 单条内容
    full = await svc.get_memory_content(uid, mid)
    assert full is not None
    assert full["content"] == "测试记忆内容：品牌A，行业电商"
    # 删除单条
    ok = await svc.delete_memory(uid, mid)
    assert ok
    full2 = await svc.get_memory_content(uid, mid)
    assert full2 is None


@requires_integration
@pytest.mark.asyncio
async def test_clear_memories() -> None:
    """clear_memories 清空该用户所有记忆条。"""
    from domain.memory import MemoryService
    from database import UserProfile, AsyncSessionLocal
    from sqlalchemy import select
    uid = "test_clear_user_xyz"
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(UserProfile).where(UserProfile.user_id == uid))
        if r.scalar_one_or_none() is None:
            session.add(UserProfile(user_id=uid))
            await session.commit()
    svc = MemoryService()
    await svc.add_memory(uid, "一条内容", "explicit")
    out = await svc.list_memories(uid)
    n_before = len(out["memory_items"])
    await svc.clear_memories(uid)
    out2 = await svc.list_memories(uid)
    assert len(out2["memory_items"]) == 0
    if n_before > 0:
        assert len(out2["memory_items"]) < n_before

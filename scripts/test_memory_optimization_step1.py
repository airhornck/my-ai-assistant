"""
记忆系统优化 - 步骤1 测试：UserMemoryItem 模型与 user_memory_items 表。
- 校验模型可导入、表名与字段存在
- 若有 DATABASE_URL，执行 create_tables 并可选插入/查询一条
"""
from __future__ import annotations

import pytest

from database import UserMemoryItem, AsyncSessionLocal, create_tables, engine
from sqlalchemy import select

try:
    from scripts.conftest import requires_integration
except ImportError:
    from conftest import requires_integration


def test_user_memory_item_model_exists() -> None:
    """UserMemoryItem 可导入且表名、关键字段存在。"""
    assert UserMemoryItem.__tablename__ == "user_memory_items"
    assert hasattr(UserMemoryItem, "id")
    assert hasattr(UserMemoryItem, "user_id")
    assert hasattr(UserMemoryItem, "content")
    assert hasattr(UserMemoryItem, "source")
    assert hasattr(UserMemoryItem, "created_at")
    assert hasattr(UserMemoryItem, "embedding_json")


@requires_integration
@pytest.mark.asyncio
async def test_create_tables_includes_user_memory_items() -> None:
    """create_tables 可执行且不报错（表若已存在则跳过）。需 DATABASE_URL。"""
    await create_tables(engine)


@requires_integration
@pytest.mark.asyncio
async def test_insert_and_select_user_memory_item() -> None:
    """能向 user_memory_items 插入一条并查出（需 DATABASE_URL，且需先有 user_profiles 对应 user_id）。"""
    from database import UserProfile

    async with AsyncSessionLocal() as session:
        # 确保有测试用户
        r = await session.execute(select(UserProfile).where(UserProfile.user_id == "test_memory_step1"))
        profile = r.scalar_one_or_none()
        if not profile:
            profile = UserProfile(user_id="test_memory_step1")
            session.add(profile)
            await session.flush()
        # 插入一条记忆（无 embedding 也可，语义召回时过滤掉）
        item = UserMemoryItem(
            user_id="test_memory_step1",
            content="测试记忆条内容",
            source="explicit",
            embedding_json=None,
        )
        session.add(item)
        await session.commit()
        mid = item.id
    # 再查
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(UserMemoryItem).where(UserMemoryItem.id == mid))
        row = r.scalar_one_or_none()
        assert row is not None
        assert row.content == "测试记忆条内容"
        assert row.source == "explicit"
    # 清理
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(UserMemoryItem).where(UserMemoryItem.user_id == "test_memory_step1"))
        for row in r.scalars().all():
            await session.delete(row)
        await session.commit()

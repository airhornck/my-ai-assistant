"""
记忆系统优化 - 步骤5 测试：get_memory_for_analyze 返回结构不变、语义 top_k 与 token 预算。
- 校验返回 dict 含 preference_context、context_fingerprint、effective_tags
- 有 DB 时可选：有记忆条时 preference_context 含【相关记忆】
"""
from __future__ import annotations

import pytest

try:
    from scripts.conftest import requires_integration
except ImportError:
    from conftest import requires_integration


def test_get_memory_for_analyze_return_shape() -> None:
    """无 DB 时也可调用（空 user_id），返回结构正确。"""
    import asyncio
    from domain.memory import MemoryService
    svc = MemoryService()
    async def _run():
        out = await svc.get_memory_for_analyze("", "", "", "", None)
        assert "preference_context" in out
        assert "context_fingerprint" in out
        assert "effective_tags" in out
        assert isinstance(out["preference_context"], str)
        assert isinstance(out["context_fingerprint"], dict)
        assert "tags" in out["context_fingerprint"]
        assert "recent_topics" in out["context_fingerprint"]
        assert isinstance(out["effective_tags"], list)
    asyncio.run(_run())


@requires_integration
@pytest.mark.asyncio
async def test_get_memory_for_analyze_with_user_returns_under_budget() -> None:
    """有 user_id 时返回的 preference_context 长度受控（约 1200 字符内）。"""
    from domain.memory import MemoryService
    svc = MemoryService()
    out = await svc.get_memory_for_analyze("test_budget_user", "品牌A", "产品B", "营销", None)
    assert len(out["preference_context"]) <= 1300  # 1200 + "…" 余量
    assert "【用户画像】" in out["preference_context"] or out["preference_context"] == ""

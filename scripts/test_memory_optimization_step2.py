"""
记忆系统优化 - 步骤2 测试：memory_embedding 封装。
- 校验 get_embedding 可导入、可调用
- 无 API Key 时返回 None；有 Key 时返回 list[float]（可选，需 DASHSCOPE_API_KEY 或等价）
"""
from __future__ import annotations

import pytest


def test_get_embedding_importable_and_callable() -> None:
    """get_embedding 可导入且可调用，空串返回 None。"""
    from services.memory_embedding import get_embedding
    assert get_embedding("") is None
    assert get_embedding("   ") is None


def test_get_embedding_returns_list_or_none() -> None:
    """有配置时返回 list，无配置时返回 None。"""
    from services.memory_embedding import get_embedding
    out = get_embedding("测试短句")
    assert out is None or (isinstance(out, list) and len(out) > 0 and all(isinstance(x, float) for x in out))

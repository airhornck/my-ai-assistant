# -*- coding: utf-8 -*-
"""
Lumina 四模块能力接口：结构校验与质量检查。
需 REDIS_URL、DATABASE_URL；涉及 AI 的接口需 DASHSCOPE_API_KEY（否则可能回退或超时）。
运行: pytest scripts/test_capability_apis.py -v -s
"""
from __future__ import annotations

import os
import pytest

try:
    from scripts.conftest import requires_integration
except ImportError:
    from conftest import requires_integration

pytestmark = [pytest.mark.asyncio, requires_integration]


async def _get(async_client, path: str, params: dict | None = None, timeout: float = 90.0):
    r = await async_client.get(
        f"http://test/api/v1/capabilities{path}",
        params=params or {},
        timeout=timeout,
    )
    return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text[:500]}


@pytest.fixture
async def client(app, async_client):
    """仅在具备集成环境时提供 client。"""
    yield async_client


class TestContentDirectionRanking:
    """1. 内容方向榜单"""

    @pytest.mark.skipif(not os.getenv("DASHSCOPE_API_KEY"), reason="content_direction_ranking 需 LLM")
    async def test_structure_and_quality(self, client):
        code, body = await _get(client, "/content-direction-ranking", {"platform": "xiaohongshu"}, timeout=120.0)
        assert code == 200, body
        assert body.get("success") is True, body
        data = body.get("data") or {}
        items = data.get("items")
        assert items is not None
        assert isinstance(items, list)
        if len(items) > 0:
            first = items[0]
            assert isinstance(first, dict)
            # 至少应有标题或角度
            assert first.get("title_suggestion") or first.get("title") or first.get("core_angle"), first
            # 若来自 content_direction_ranking，应有适配度或风险
            if body.get("source") == "content_direction_ranking":
                assert "adaptation_score" in first or "risk_level" in first or first.get("angles") is not None, first


class TestCaseLibrary:
    """2. 定位决策案例库"""

    async def test_structure(self, client):
        code, body = await _get(client, "/case-library", {"page": 1, "page_size": 5})
        assert code == 200, body
        assert body.get("success") is True, body
        data = body.get("data") or {}
        items = data.get("items", data.get("list", []))
        assert isinstance(items, list)


class TestContentPositioningMatrix:
    """3. 内容定位矩阵"""

    async def test_structure_and_matrix_size(self, client):
        code, body = await _get(client, "/content-positioning-matrix", {"industry": "教育"})
        assert code == 200, body
        assert body.get("success") is True, body
        data = body.get("data") or {}
        matrix = data.get("matrix")
        assert matrix is not None
        assert isinstance(matrix, list)
        assert len(matrix) == 12, f"期望 3x4=12 格，实际 {len(matrix)}"
        for i, cell in enumerate(matrix):
            assert isinstance(cell, dict), f"matrix[{i}]"
            for key in ("priority", "stage", "boundary", "suggestion", "example"):
                assert key in cell, f"matrix[{i}] 缺少 {key}"
        assert isinstance(data.get("persona"), (dict, type(None)))


class TestWeeklyDecisionSnapshot:
    """4. 每周决策快照"""

    @pytest.mark.skipif(not os.getenv("DASHSCOPE_API_KEY"), reason="weekly_focus 可能调 LLM")
    async def test_structure_and_quality(self, client):
        code, body = await _get(client, "/weekly-decision-snapshot", {"user_id": "test_verify"}, timeout=120.0)
        assert code == 200, body
        assert body.get("success") is True, body
        data = body.get("data") or {}
        for key in ("stage", "max_risk", "priorities", "forbidden", "weekly_focus", "history"):
            assert key in data, f"缺少 data.{key}"
        assert isinstance(data["priorities"], list)
        assert isinstance(data["forbidden"], list)
        assert isinstance(data["history"], list)
        assert len(data["forbidden"]) >= 1, "禁区应有至少一条默认说明"

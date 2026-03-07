"""
记忆系统优化 - 步骤7 测试：GET/DELETE 记忆 API（列表、内容查看、清空、单条删）。
需启动应用或使用 TestClient；需 DATABASE_URL。
"""
from __future__ import annotations

import pytest

try:
    from scripts.conftest import requires_integration
except ImportError:
    from conftest import requires_integration


@requires_integration
def test_get_memory_list_api(app) -> None:
    """GET /api/v1/memory 返回 200 且含 profile_summary、memory_items、recent_interaction_count。"""
    from fastapi.testclient import TestClient
    client = TestClient(app)
    r = client.get("/api/v1/memory", params={"user_id": "test_api_user"})
    assert r.status_code == 200
    data = r.json()
    assert "profile_summary" in data
    assert "memory_items" in data
    assert "recent_interaction_count" in data


@requires_integration
def test_get_memory_content_404(app) -> None:
    """GET /api/v1/memory/999999 在无该条或归属不同时返回 404。"""
    from fastapi.testclient import TestClient
    client = TestClient(app)
    r = client.get("/api/v1/memory/999999", params={"user_id": "test_api_user"})
    assert r.status_code == 404


@requires_integration
def test_clear_memory_api(app) -> None:
    """DELETE /api/v1/memory 返回 200。"""
    from fastapi.testclient import TestClient
    client = TestClient(app)
    r = client.delete("/api/v1/memory", params={"user_id": "test_api_user"})
    assert r.status_code == 200
    assert r.json().get("success") is True

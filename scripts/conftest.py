"""
pytest 公共配置与 fixtures。
测试脚本可独立运行：pytest scripts/ -v
集成测试需 REDIS_URL、DATABASE_URL；涉及 AI 的用例需 DASHSCOPE_API_KEY。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# pytest-asyncio：异步用例使用 asyncio
pytest_plugins = ["pytest_asyncio"]

# 将项目根目录加入 path，便于 import main
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 加载 .env（若存在）
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _has_integration_env() -> bool:
    """是否有集成测试所需环境（Redis + 数据库）。"""
    return bool(os.getenv("REDIS_URL") and os.getenv("DATABASE_URL"))


def _has_ai_env() -> bool:
    """是否有 AI 调用所需 API Key。"""
    return bool(os.getenv("DASHSCOPE_API_KEY"))


# 标记：集成测试（需 Redis + DB）
requires_integration = pytest.mark.skipif(
    not _has_integration_env(),
    reason="需要 REDIS_URL 与 DATABASE_URL",
)

# 标记：需 AI（需 DASHSCOPE_API_KEY）
requires_ai = pytest.mark.skipif(
    not _has_ai_env(),
    reason="需要 DASHSCOPE_API_KEY",
)


@pytest.fixture(scope="session")
def app():
    """FastAPI 应用实例（不启动 HTTP 服务）。"""
    from main import app as _app
    return _app


@pytest.fixture
async def async_client(app):
    """
    异步 HTTP 客户端：在应用 lifespan 内运行，可调用全部路由。
    仅当 REDIS_URL、DATABASE_URL 存在时可用，否则跳过。
    """
    if not _has_integration_env():
        pytest.skip("需要 REDIS_URL 与 DATABASE_URL 以运行集成测试")
    import httpx
    # 进入 lifespan，使 session_manager、db、ai_service 等可用
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=60.0,
        ) as client:
            yield client

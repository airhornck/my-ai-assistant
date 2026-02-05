"""
多轮闲聊与创作意图切换测试：验证会话意图、建议内容、上下文是否在切换中丢失。
场景：你好(闲聊) → 推广华为手机(创作) → 还好(闲聊) → 可以的(采纳建议) → 你好(闲聊)
断言：每轮意图正确、创作轮次保留 topic/华为、采纳后不以「可以的」为话题、闲聊轮次不丢会话意图。

运行方式：
- 单元（不依赖 DB/Redis）：pytest scripts/test_multi_turn_context.py::test_short_casual_replies_set -v
- 集成（需 PostgreSQL + Redis 已启动）：pytest scripts/test_multi_turn_context.py -v -s
  需 REDIS_URL、DATABASE_URL；涉及创作/采纳的用例需 DASHSCOPE_API_KEY，单轮创作耗时可至 1–2 分钟。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# 单元测试（无 DB/Redis，可单独跑）
# ---------------------------------------------------------------------------


def test_short_casual_replies_set():
    """极短闲聊集合包含「你好」「还好」，保证意图与策略脑快路径能识别。"""
    from core.intent.processor import SHORT_CASUAL_REPLIES
    assert "你好" in SHORT_CASUAL_REPLIES, "「你好」应在 SHORT_CASUAL_REPLIES 中以便直接判闲聊"
    assert "还好" in SHORT_CASUAL_REPLIES, "「还好」应在 SHORT_CASUAL_REPLIES 中以便直接判闲聊"
    assert "您好" in SHORT_CASUAL_REPLIES
    assert len(SHORT_CASUAL_REPLIES) >= 10, "应包含问候与简短寒暄"


def _has_integration_env() -> bool:
    return bool(os.getenv("REDIS_URL") and os.getenv("DATABASE_URL"))


def _has_ai_env() -> bool:
    return bool(os.getenv("DASHSCOPE_API_KEY"))


@pytest.fixture(scope="session")
def app():
    from main import app as _app
    return _app


@pytest.fixture
async def async_client(app):
    if not _has_integration_env():
        pytest.skip("需要 REDIS_URL 与 DATABASE_URL")
    import httpx
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=130.0,
        ) as client:
            yield client


@pytest.mark.asyncio
@pytest.mark.skipif(not _has_integration_env(), reason="需要 REDIS_URL 与 DATABASE_URL")
async def test_multi_turn_casual_creation_context(async_client):
    """
    多轮闲聊↔创作切换：验证意图与上下文不丢失。
    轮次：你好 → 推广华为手机 → 还好 → 可以的(采纳) → 你好
    """
    # 1. 初始化会话
    r_init = await async_client.get("/api/v1/frontend/session/init")
    assert r_init.status_code == 200, r_init.text
    data_init = r_init.json()
    assert data_init.get("success") is True, data_init
    user_id = data_init.get("user_id")
    session_id = data_init.get("session_id")
    assert user_id and session_id

    history = []

    # 2. 第 1 轮：闲聊「你好」
    r1 = await async_client.post(
        "/api/v1/frontend/chat",
        json={
            "message": "你好",
            "session_id": session_id,
            "user_id": user_id,
            "history": history,
        },
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1.get("success") is True, d1.get("error", d1)
    resp1 = (d1.get("response") or "").strip()
    assert len(resp1) > 0, "第1轮应有回复"
    # 闲聊不应返回大段「深度思考报告」
    assert "深度思考报告" not in resp1 or len(resp1) < 500, "第1轮应为闲聊回复而非创作报告"
    history.append({"role": "user", "content": "你好"})
    history.append({"role": "assistant", "content": resp1})

    # 3. 第 2 轮：创作「推广华为手机，目标年轻人」
    if not _has_ai_env():
        pytest.skip("需要 DASHSCOPE_API_KEY 以执行创作轮")
    r2 = await async_client.post(
        "/api/v1/frontend/chat",
        json={
            "message": "推广华为手机，目标年轻人",
            "session_id": session_id,
            "user_id": user_id,
            "history": history,
        },
        timeout=130.0,
    )
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2.get("success") is True, d2.get("error", d2)
    resp2 = (d2.get("response") or "").strip()
    assert len(resp2) > 0, "第2轮应有回复"
    # 创作应包含与主题相关或深度报告
    assert "华为" in resp2 or "手机" in resp2 or "深度思考" in resp2 or "思维链" in resp2, (
        "第2轮应为创作内容且与华为/手机相关，resp 前 300 字: " + resp2[:300]
    )
    intent2 = d2.get("intent", "")
    assert intent2 in ("creation", "free_discussion", "structured_request", ""), "第2轮意图应为创作类"
    history.append({"role": "user", "content": "推广华为手机，目标年轻人"})
    history.append({"role": "assistant", "content": resp2[:500]})  # 模拟前端截断

    # 4. 第 3 轮：闲聊「还好」—— 会话意图应保留，不应丢 topic
    r3 = await async_client.post(
        "/api/v1/frontend/chat",
        json={
            "message": "还好",
            "session_id": session_id,
            "user_id": user_id,
            "history": history,
        },
    )
    assert r3.status_code == 200, r3.text
    d3 = r3.json()
    assert d3.get("success") is True, d3.get("error", d3)
    resp3 = (d3.get("response") or "").strip()
    assert len(resp3) > 0, "第3轮应有回复"
    # 闲聊应为短回复，不应又是大段创作报告
    assert "深度思考报告" not in resp3 or len(resp3) < 600, "第3轮应为闲聊回复，不应输出完整创作报告"
    history.append({"role": "user", "content": "还好"})
    history.append({"role": "assistant", "content": resp3[:500]})

    # 5. 第 4 轮：采纳建议「可以的」—— 应延续上轮创作话题（华为手机），不应以「可以的」为话题
    r4 = await async_client.post(
        "/api/v1/frontend/chat",
        json={
            "message": "可以的",
            "session_id": session_id,
            "user_id": user_id,
            "history": history,
        },
        timeout=130.0,
    )
    assert r4.status_code == 200, r4.text
    d4 = r4.json()
    assert d4.get("success") is True, d4.get("error", d4)
    resp4 = (d4.get("response") or "").strip()
    assert len(resp4) > 0, "第4轮应有回复"
    # 采纳后应走创作，且不应出现「围绕"可以的"」等错误话题
    assert "可以的" not in resp4 or "围绕" not in resp4, (
        "采纳建议后不应以「可以的」为话题，resp 前 400 字: " + resp4[:400]
    )
    # 若为创作输出，应仍与华为/手机/推广相关
    if "深度思考" in resp4 or "思维链" in resp4 or len(resp4) > 200:
        assert "华为" in resp4 or "手机" in resp4 or "推广" in resp4 or "文案" in resp4, (
            "采纳后创作应延续华为手机主题，resp 前 400 字: " + resp4[:400]
        )
    history.append({"role": "user", "content": "可以的"})
    history.append({"role": "assistant", "content": resp4[:500]})

    # 6. 第 5 轮：再次闲聊「你好」—— 会话仍有效，回复为闲聊
    r5 = await async_client.post(
        "/api/v1/frontend/chat",
        json={
            "message": "你好",
            "session_id": session_id,
            "user_id": user_id,
            "history": history,
        },
    )
    assert r5.status_code == 200, r5.text
    d5 = r5.json()
    assert d5.get("success") is True, d5.get("error", d5)
    resp5 = (d5.get("response") or "").strip()
    assert len(resp5) > 0, "第5轮应有回复"
    assert "深度思考报告" not in resp5 or len(resp5) < 500, "第5轮应为闲聊回复"


@pytest.mark.asyncio
@pytest.mark.skipif(not _has_integration_env(), reason="需要 REDIS_URL 与 DATABASE_URL")
async def test_short_casual_replies_no_llm(async_client):
    """
    极短闲聊（你好、还好）不调用意图 LLM，直接走策略脑快路径；回复为闲聊。
    """
    r_init = await async_client.get("/api/v1/frontend/session/init")
    assert r_init.status_code == 200
    data_init = r_init.json()
    assert data_init.get("success") is True
    user_id = data_init.get("user_id")
    session_id = data_init.get("session_id")
    assert user_id and session_id

    for msg in ("你好", "还好"):
        r = await async_client.post(
            "/api/v1/frontend/chat",
            json={
                "message": msg,
                "session_id": session_id,
                "user_id": user_id,
                "history": [],
            },
        )
        assert r.status_code == 200, f"message={msg} {r.text}"
        d = r.json()
        assert d.get("success") is True, d.get("error", d)
        resp = (d.get("response") or "").strip()
        assert len(resp) > 0, f"message={msg} 应有回复"
        assert "深度思考报告" not in resp or len(resp) < 500, f"message={msg} 应为闲聊而非完整报告"

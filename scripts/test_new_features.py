"""
全流程验证：自由文本、结构化输入、/new_chat 命令、文档上传与查询、插件总线路由。
独立运行：pytest scripts/test_new_features.py -v
集成测试需 REDIS_URL、DATABASE_URL；涉及深度分析的用例需 DASHSCOPE_API_KEY。
"""
from __future__ import annotations

import io
import os
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# 确保项目根在 path 中（conftest 已做，此处防御性添加）
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# 单元测试（无 Redis/DB，可独立运行）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_bus_document_query_routing():
    """插件总线能正确路由 DocumentQueryEvent，插件可写回 enhanced。"""
    from core.plugin_bus import (
        DOCUMENT_QUERY,
        BasePlugin,
        DocumentQueryEvent,
        PluginBus,
        PluginEvent,
    )

    handled: list[PluginEvent] = []
    enhanced_value = {"structured_data": {"topic": "from_plugin"}}

    class DocQueryPlugin(BasePlugin):
        async def can_handle(self, event: PluginEvent) -> bool:
            return event.event_type == DOCUMENT_QUERY

        async def handle(self, event: PluginEvent) -> Optional[PluginEvent]:
            handled.append(event)
            if event.data is not None:
                event.data["enhanced"] = enhanced_value
            return None

    bus = PluginBus()
    await bus.register(DocQueryPlugin())
    payload: Dict[str, Any] = {
        "processed_input": {"intent": DOCUMENT_QUERY, "raw_query": "根据文档总结"},
        "user_id": "test_user",
        "session_id": "test_session",
        "enhanced": None,
    }
    # model_construct 保留 data 引用，插件对 event.data 的修改会反映到 payload
    event = DocumentQueryEvent.model_construct(source="test", data=payload)
    await bus.publish(event)

    assert len(handled) == 1
    assert handled[0].event_type == DOCUMENT_QUERY
    assert payload.get("enhanced") == enhanced_value


@pytest.mark.asyncio
async def test_input_processor_command_new_chat():
    """输入 /new_chat 时，不调用 AI，直接返回 intent=command、command=new_chat。"""
    from services.input_service import InputProcessor, INTENT_COMMAND

    # 命令由正则优先识别，不经过 AI；注入占位 mock 避免无 API Key 时实例化 SimpleAIService 失败
    processor = InputProcessor(ai_service=MagicMock())
    result = await processor.process(
        raw_input="/new_chat",
        session_id="s1",
        user_id="u1",
    )
    assert result.get("intent") == INTENT_COMMAND
    assert result.get("command") == "new_chat"
    assert result.get("raw_query", "").strip() == "/new_chat"


@pytest.mark.asyncio
async def test_input_processor_free_text_mocked():
    """自由文本经 mock AI 识别后，返回预期 intent 与 raw_query。"""
    from services.input_service import InputProcessor, INTENT_FREE_DISCUSSION

    raw = "我想推广一个新款降噪耳机，主打年轻音乐爱好者。"
    fake_content = '''```json
{"intent": "free_discussion", "brand_name": "", "product_desc": "", "topic": "", "command": ""}
```'''

    mock_client = MagicMock()
    mock_client.ainvoke = AsyncMock(return_value=MagicMock(content=fake_content))
    mock_router = MagicMock()
    mock_router.route = AsyncMock(return_value=mock_client)
    mock_ai = MagicMock(router=mock_router)

    processor = InputProcessor(ai_service=mock_ai)
    result = await processor.process(raw_input=raw, session_id="s1", user_id="u1")

    assert result.get("intent") == INTENT_FREE_DISCUSSION
    assert result.get("raw_query") == raw


# ---------------------------------------------------------------------------
# 集成测试（需 REDIS_URL、DATABASE_URL，由 conftest 提供 async_client）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("async_client")
async def test_api_new_chat_command(async_client):
    """POST /api/v1/analyze-deep/raw 发送 /new_chat，返回 intent=command、command=new_chat。"""
    r = await async_client.post(
        "/api/v1/analyze-deep/raw",
        json={"user_id": "test_user_raw", "raw_input": "/new_chat"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    assert data.get("intent") == "command"
    assert data.get("command") == "new_chat"
    assert "session_id" in data


@pytest.mark.asyncio
@pytest.mark.usefixtures("async_client")
async def test_api_chat_new_creates_thread_and_session(async_client):
    """POST /api/v1/chat/new 创建新对话链，返回 thread_id 与 session_id。"""
    r = await async_client.post(
        "/api/v1/chat/new",
        json={"user_id": "test_user_chat_new"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    assert "thread_id" in data and len(data["thread_id"]) > 0
    assert "session_id" in data and len(data["session_id"]) > 0


# 最小合法 PDF 字节（仅用于验证上传与存储）
MINIMAL_PDF_BYTES = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000052 00000 n 
0000000101 00000 n 
trailer<</Size 4/Root 1 0 R>>
startxref
178
%%EOF
"""


@pytest.mark.asyncio
@pytest.mark.usefixtures("async_client")
async def test_api_upload_pdf_and_list(async_client):
    """上传 PDF 后，文档成功存储且 GET /api/v1/documents 可查到元信息。"""
    user_id = "test_user_doc_upload"
    session_id = "test_session_upload_001"
    files = {"file": ("test.pdf", io.BytesIO(MINIMAL_PDF_BYTES), "application/pdf")}
    data_form = {"user_id": user_id, "session_id": session_id}

    r = await async_client.post(
        "/api/v1/documents/upload",
        data=data_form,
        files=files,
    )
    assert r.status_code == 200
    up = r.json()
    assert up.get("success") is True
    doc = up.get("data", {})
    assert "doc_id" in doc
    assert doc.get("user_id") == user_id
    assert "storage_path" in doc
    assert "upload_time" in doc

    list_r = await async_client.get("/api/v1/documents", params={"session_id": session_id})
    assert list_r.status_code == 200
    list_data = list_r.json()
    assert list_data.get("success") is True
    items = list_data.get("data", [])
    assert any(d.get("doc_id") == doc["doc_id"] for d in items)


@pytest.mark.asyncio
@pytest.mark.usefixtures("async_client")
async def test_api_structured_input(async_client):
    """结构化输入：POST /api/v1/analyze-deep（JSON），返回 session_id；若无 AI Key 则跳过。"""
    if not os.getenv("DASHSCOPE_API_KEY"):
        pytest.skip("需要 DASHSCOPE_API_KEY 以执行元工作流")
    r = await async_client.post(
        "/api/v1/analyze-deep",
        json={
            "user_id": "test_user_structured",
            "brand_name": "TestBrand",
            "product_desc": "降噪耳机",
            "topic": "年轻音乐爱好者推广",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    assert "session_id" in data
    assert "data" in data


@pytest.mark.asyncio
@pytest.mark.usefixtures("async_client")
async def test_api_free_text_input(async_client):
    """自由文本：POST /api/v1/analyze-deep/raw，返回正确 intent 与结果结构；若无 AI Key 则跳过。"""
    if not os.getenv("DASHSCOPE_API_KEY"):
        pytest.skip("需要 DASHSCOPE_API_KEY 以执行意图识别与元工作流")
    r = await async_client.post(
        "/api/v1/analyze-deep/raw",
        json={
            "user_id": "test_user_free",
            "raw_input": "我想推广一个新款降噪耳机，主打年轻音乐爱好者。",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    assert "intent" in data
    assert data["intent"] in ("free_discussion", "structured_request", "casual_chat", "document_query", "command", "clarification")
    assert "session_id" in data
    assert "data" in data or "thinking_process" in data


# 集成测试依赖 conftest 的 async_client，缺 REDIS_URL/DATABASE_URL 时该 fixture 会 skip，对应用例自动跳过。
# 单元测试（前三个）不依赖 Redis/DB，可独立运行。

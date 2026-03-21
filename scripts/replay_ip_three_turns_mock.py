#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
三轮 IP（intake -> intake -> executing）最小回放验证：
- 使用 Mock LLM + stub web/memory，避免真实外部依赖
- 直接调用 workflows.meta_workflow.build_meta_workflow 构建的 LangGraph
- 断言第三轮（补齐必填后）返回 phase=executing，且 content 非空
- 打印固定模板 ID、人类可读说明、plan 步骤列表

说明（固定 plan「执行」到哪一步）：
- 第三轮在同一轮 ainvoke 内会完成：intake 合并 → plan_once（resolve 固定模板 + 写入 plan）
- 图在 ip_build_router 结束（ip_build_handled），**不会在同一次调用里跑 execute_one_step**
  （analyze/generate 等需第四轮及以后 phase=executing 再继续）

运行：
  python scripts/replay_ip_three_turns_mock.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import workflows.meta_workflow as meta_mod  # noqa: E402
from plans import PLAN_TEMPLATE_DYNAMIC, get_template_meta  # noqa: E402


def _configure_stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _print_turn_plan_report(out: dict, label: str) -> None:
    """打印本轮选中的模板与步骤，便于确认是否走固定 plan。"""
    tid = (out.get("plan_template_id") or "").strip()
    meta = get_template_meta(tid) if tid else None
    pname = (meta or {}).get("name", "") if meta else ""
    desc = (meta or {}).get("description", "") if meta else ""
    is_fixed = bool(tid) and tid != PLAN_TEMPLATE_DYNAMIC
    plan = out.get("plan") or []
    steps_summary = [(s or {}).get("step", "?") for s in plan if isinstance(s, dict)]
    print(f"--- {label} ---")
    print(f"  plan_template_id: {tid!r}")
    if pname:
        print(f"  模板展示名(name): {pname}")
    print(f"  是否固定模板: {is_fixed}（dynamic 表示当轮走了 LLM 动态规划）")
    if desc:
        print(f"  模板说明(description): {desc}")
    print(f"  步骤数: {len(plan)}  步骤序列: {steps_summary}")


class _DummyGraph:
    async def ainvoke(self, *args: Any, **kwargs: Any) -> dict:
        return {}


class _DummyLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class MockLLM:
    """
    只需要支持 IntentAgent.classify_intent 用到的 `await llm.invoke(messages)`。
    返回固定偏高置信度，避免走 need_clarification 分支。
    """

    async def invoke(self, messages: list[Any], *args: Any, **kwargs: Any) -> _DummyLLMResponse:
        return _DummyLLMResponse(
            json.dumps(
                {
                    "intent": "free_discussion",
                    "confidence": 0.9,
                    "raw_query": "",
                    "notes": "mock_intent",
                },
                ensure_ascii=False,
            )
        )


@dataclass
class _StubWebSearcher:
    async def search(self, query: str, num_results: int = 3) -> list[dict]:
        return []

    def format_results_as_context(self, results: list[dict]) -> str:
        return ""


@dataclass
class _StubMemoryService:
    async def get_memory_for_analyze(self, *args: Any, **kwargs: Any) -> dict:
        return {"preference_context": "", "effective_tags": []}

    async def get_user_summary(self, *args: Any, **kwargs: Any) -> str:
        return ""


@dataclass
class _StubKnowledgePort:
    async def retrieve(self, *args: Any, **kwargs: Any) -> list[str]:
        return []


@dataclass
class _StubAIService:
    _llm: Any


def _make_user_input_payload(raw_query: str) -> str:
    payload = {
        "raw_query": raw_query,
        "brand_name": "",
        "product_desc": "",
        "topic": "",
        "conversation_context": "",
        "tags": [],
    }
    return json.dumps(payload, ensure_ascii=False)


async def main() -> None:
    _configure_stdout_utf8()
    # Monkeypatch：避免 build_meta_workflow 在不走 analyze/generate 时还构建真实子图
    meta_mod.build_analysis_brain_subgraph = lambda ai_svc: _DummyGraph()
    meta_mod.build_generation_brain_subgraph = lambda ai_svc: _DummyGraph()

    ai_svc = _StubAIService(_llm=MockLLM())
    web = _StubWebSearcher()
    mem = _StubMemoryService()
    kb = _StubKnowledgePort()

    workflow = meta_mod.build_meta_workflow(
        ai_service=ai_svc,
        web_searcher=web,
        memory_service=mem,
        knowledge_port=kb,
    )

    thread_id = "replay_thread_mock"
    config = {"configurable": {"thread_id": thread_id}}

    # 关键：我们显式把 phase 设为 intake，让 ip_build_router_node 接管三轮。
    # 第三轮补齐后应进入 executing，并且 content 非空（由我们的一致性兜底文案保证）。
    state0 = {
        "user_input": _make_user_input_payload("你好"),
        "analysis": "",
        "content": "",
        "session_id": "replay_session_mock",
        "user_id": "replay_user_mock",
        "evaluation": {},
        "need_revision": False,
        "stage_durations": {},
        "analyze_cache_hit": False,
        "used_tags": [],
        "plan": [],
        "task_type": "",
        "current_step": 0,
        "thinking_logs": [],
        "step_outputs": [],
        "search_context": "",
        "memory_context": "",
        "kb_context": "",
        "effective_tags": [],
        "analysis_plugins": [],
        "generation_plugins": [],
        "phase": "intake",
        "ip_context": {},
        "pending_questions": [],
        "plan_template_id": "",
    }

    out1 = await workflow.ainvoke(state0, config=config)
    assert out1.get("phase") == "intake"
    assert out1.get("pending_questions") or []

    state1 = {**state0, **out1}
    state1["user_input"] = _make_user_input_payload("我想推广产品")
    state1["phase"] = "intake"

    out2 = await workflow.ainvoke(state1, config=config)
    assert out2.get("phase") == "intake"
    # 第二轮通常只缺 brand_name（视 infer_fields 输出而定）

    state2 = {**state1, **out2}
    state2["user_input"] = _make_user_input_payload("我是个体商户，我是做教育的，目前还没有自己的账号，我想打造一个账号")
    state2["phase"] = "intake"

    out3 = await workflow.ainvoke(state2, config=config)
    phase3 = out3.get("phase")
    content3 = (out3.get("content") or "").strip()

    print("Turn1 phase:", out1.get("phase"))
    print("Turn2 phase:", out2.get("phase"))
    print("Turn3 phase:", phase3)
    print("Turn3 content:", content3)
    print("Turn3 pending_questions:", out3.get("pending_questions"))
    _print_turn_plan_report(out3, "Turn3（补齐后：应已加载固定/动态 plan，尚未在同轮执行各 step）")
    print(
        "提示: 本脚本仅验证第三轮已写入 plan 并 phase=executing；"
        "若需验证 execute_one_step，请增加第四轮 state.phase='executing' 的 ainvoke。"
    )

    assert phase3 == "executing", f"期望 third turn phase=executing，但得到 {phase3}"
    assert content3, "期望 third turn content 非空（用于前端稳定展示/避免用户误以为卡住）"
    # 本用例第三轮用户话术中含「账号/打造」，registry 应匹配账号打造固定模板
    assert out3.get("plan_template_id") == "account_building", (
        f"期望固定模板 account_building，实际 plan_template_id={out3.get('plan_template_id')!r}"
    )
    plan3 = out3.get("plan") or []
    assert len(plan3) >= 1, "期望 plan 已物化为非空步骤列表"


if __name__ == "__main__":
    asyncio.run(main())


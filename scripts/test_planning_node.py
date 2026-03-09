#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 meta_workflow.planning_node：策略脑规划逻辑与 explicit_content_request 过滤。
可单独运行：python scripts/test_planning_node.py
或：pytest scripts/test_planning_node.py -v -s
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


async def _run_planning_node(user_input_payload: dict) -> dict:
    """构建 meta workflow，用 astream(stream_mode=\"updates\") 只取 planning 节点输出。"""
    from workflows.meta_workflow import build_meta_workflow
    from workflows.types import MetaState
    workflow = build_meta_workflow()
    state: MetaState = {
        "user_input": json.dumps(user_input_payload, ensure_ascii=False),
        "session_id": "test_session",
        "user_id": "test_user",
    }
    config = {"configurable": {"thread_id": "test_planning_thread"}}
    # 只取第一个节点（planning）的更新，避免跑完整图
    async for chunk in workflow.astream(state, config=config, stream_mode="updates"):
        if "planning" in chunk:
            return dict(chunk["planning"])
    # 若未 stream 到 planning（如图结构变化），退化为 ainvoke 取最终 state
    out = await workflow.ainvoke(state, config=config)
    return dict(out)


def test_planning_explicit_generate_has_generate_step() -> None:
    """明确要求生成时，plan 应包含 generate 步骤。"""
    async def _run():
        payload = {
            "raw_query": "帮我写一篇小红书文案",
            "brand_name": "测试品牌",
            "topic": "新品推广",
        }
        out = await _run_planning_node(payload)
        plan = out.get("plan") or []
        steps = [str(s.get("step", "")).lower() for s in plan if isinstance(s, dict)]
        assert "generate" in steps, f"明确生成请求下 plan 应含 generate，实际: {steps}"
        assert out.get("task_type") or len(plan) > 0
        print("[OK] 明确生成请求 → plan 含 generate:", steps)

    asyncio.run(_run())


def test_planning_casual_no_generate_step() -> None:
    """闲聊/未明确生成时，plan 不应包含 generate。"""
    async def _run():
        payload = {
            "raw_query": "你好，今天天气怎么样",
            "intent": "闲聊",
        }
        out = await _run_planning_node(payload)
        plan = out.get("plan") or []
        steps = [str(s.get("step", "")).lower() for s in plan if isinstance(s, dict)]
        assert "generate" not in steps, f"闲聊时 plan 不应含 generate，实际: {steps}"
        print("[OK] 闲聊请求 → plan 不含 generate:", steps)

    asyncio.run(_run())


def test_planning_fallback_structure() -> None:
    """兜底时返回结构应包含 plan、task_type、thinking_logs；可选 planning_duration_sec。"""
    async def _run():
        payload = {"raw_query": "测试"}
        out = await _run_planning_node(payload)
        assert "plan" in out and isinstance(out["plan"], list), f"缺少 plan: {list(out.keys())}"
        assert "task_type" in out
        assert "thinking_logs" in out and isinstance(out["thinking_logs"], list)
        assert out.get("current_step") == 0
        if "planning_duration_sec" in out:
            print("[OK] 返回结构完整(含 planning_duration_sec), plan 长度:", len(out["plan"]))
        else:
            print("[OK] 返回结构完整, plan 长度:", len(out["plan"]), "(无 planning_duration_sec)")
    asyncio.run(_run())


if __name__ == "__main__":
    print("需要 REDIS_URL、DATABASE_URL；若未配置可能报错。")
    print("运行 planning_node 测试...")
    test_planning_fallback_structure()
    test_planning_casual_no_generate_step()
    test_planning_explicit_generate_has_generate_step()
    print("全部通过。")

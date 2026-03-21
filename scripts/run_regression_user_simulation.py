#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
模拟用户整体回归测试：不启动 HTTP 服务，直接调用 meta_workflow，覆盖多种用户场景。
覆盖：闲聊、生成内容、账号诊断、查询信息、多轮上下文、极短句等，校验流程不崩溃且返回结构正确。

场景列表：
  1. 闲聊-你好 / 谢谢 / 在吗
  2. 生成-小红书文案（品牌+话题）
  3. 账号诊断（我的账号最近流量不好）
  4. 查询信息（想提升账号流量有什么办法）
  5. 策略规划（制定推广策略）
  6. 多轮-上下文（小红书吧 + 对话上下文）
  7. 模糊输入-短句（在吗）

使用：
  python scripts/run_regression_user_simulation.py
  pytest scripts/run_regression_user_simulation.py -v -s
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _f in (".env", ".env.dev"):
    _p = ROOT / _f
    if _p.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(_p)
        except ImportError:
            pass
        break

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _make_state(
    raw_query: str,
    user_id: str = "regression_user",
    session_id: str | None = None,
    brand_name: str = "",
    product_desc: str = "",
    topic: str = "",
    conversation_context: str = "",
) -> dict:
    """构造与 frontend/chat 一致的 user_input payload 与 initial_state。"""
    sid = session_id or f"regression_{int(time.time())}"
    payload = {
        "user_id": user_id,
        "session_id": sid,
        "brand_name": brand_name,
        "product_desc": product_desc,
        "topic": topic,
        "raw_query": raw_query,
        "conversation_context": conversation_context or None,
        "tags": [],
    }
    return {
        "user_input": json.dumps(payload, ensure_ascii=False),
        "analysis": "",
        "content": "",
        "session_id": sid,
        "user_id": user_id,
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
    }


# 场景：(名称, raw_query, 可选 brand/topic/context, 期望：plan 含某步 / 有 content / 等)
SCENARIOS = [
    {
        "name": "闲聊-你好",
        "state": _make_state("你好"),
        "expect": {"has_plan": True, "casual_or_content": True},
    },
    {
        "name": "闲聊-谢谢",
        "state": _make_state("谢谢"),
        "expect": {"has_plan": True, "casual_or_content": True},
    },
    {
        "name": "生成-小红书文案",
        "state": _make_state(
            "帮我生成一篇小红书文案",
            brand_name="测试品牌",
            topic="新品推广",
        ),
        "expect": {"has_plan": True, "has_generate_step": True, "has_content_or_analysis": True},
    },
    {
        "name": "账号诊断",
        "state": _make_state("我的账号最近流量不好", brand_name="测试账号"),
        "expect": {"has_plan": True, "has_content_or_analysis": True},
    },
    {
        "name": "查询信息",
        "state": _make_state("想提升账号流量有什么办法"),
        "expect": {"has_plan": True, "casual_or_content": True},
    },
    {
        "name": "策略规划",
        "state": _make_state(
            "帮我制定一个推广策略",
            brand_name="某手机品牌",
            topic="618大促",
        ),
        "expect": {"has_plan": True, "has_content_or_analysis": True},
    },
    {
        "name": "多轮-上下文",
        "state": _make_state(
            "小红书吧",
            topic="女装推广",
            conversation_context="用户：我想做女装推广\n助手：您有指定平台吗？",
        ),
        "expect": {"has_plan": True, "casual_or_content": True},
    },
    {
        "name": "模糊输入-短句",
        "state": _make_state("在吗"),
        "expect": {"has_plan": True, "casual_or_content": True},
    },
]


async def run_one(
    workflow,
    scenario: dict,
    thread_id: str,
    timeout: float = 120.0,
) -> tuple[str, bool, str, dict]:
    """跑单场景，返回 (名称, 是否通过, 错误信息, 结果摘要)。"""
    name = scenario["name"]
    state = scenario["state"]
    expect = scenario["expect"]
    config = {"configurable": {"thread_id": thread_id}}
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            workflow.ainvoke(state, config=config),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return name, False, "超时", {"duration": timeout}
    except Exception as e:
        return name, False, str(e), {"duration": time.perf_counter() - t0}
    duration = time.perf_counter() - t0

    plan = result.get("plan") or []
    content = (result.get("content") or "").strip()
    analysis = result.get("analysis")
    steps = [str(s.get("step", "")).lower() for s in plan if isinstance(s, dict)]
    has_generate = "generate" in steps
    has_content = len(content) > 0
    has_analysis = isinstance(analysis, dict) and bool(analysis) or isinstance(analysis, str) and bool((analysis or "").strip())

    err = []
    if expect.get("has_plan") and not plan:
        err.append("期望有 plan")
    if expect.get("has_generate_step") and not has_generate:
        err.append("期望 plan 含 generate")
    if expect.get("has_content_or_analysis") and not (has_content or has_analysis):
        err.append("期望有 content 或 analysis")
    if expect.get("casual_or_content") and not (has_content or len(plan) == 1 and (plan[0].get("step") or "").lower() == "casual_reply"):
        # 闲聊可能只有 casual_reply 一步且有 content
        if not has_content and not (plan and (plan[0].get("step") or "").lower() == "casual_reply"):
            err.append("期望闲聊回复或单步 casual_reply")
    passed = len(err) == 0
    return name, passed, "; ".join(err) if err else "", {
        "duration": round(duration, 2),
        "intent": result.get("intent", ""),
        "steps": steps,
        "content_len": len(content),
        "has_analysis": has_analysis,
    }


async def main() -> int:
    print("=" * 64)
    print("模拟用户整体回归测试（meta_workflow 直调）")
    print("=" * 64)
    if not os.getenv("DASHSCOPE_API_KEY"):
        print("提示: 未设置 DASHSCOPE_API_KEY 时，意图/策略走 fallback，部分断言可能放宽。")
    print()

    try:
        from workflows.meta_workflow import build_meta_workflow
    except Exception as e:
        print(f"构建工作流失败: {e}")
        return 1

    meta = build_meta_workflow()
    thread_base = f"regression_{int(time.time())}"
    results = []
    for i, scenario in enumerate(SCENARIOS):
        name, passed, err, summary = await run_one(
            meta,
            scenario,
            thread_id=f"{thread_base}_{i}",
        )
        results.append((name, passed, err, summary))
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}  {summary.get('duration', 0):.1f}s  intent={summary.get('intent', '')}  steps={summary.get('steps', [])}")
        if err:
            print(f"         {err}")

    print()
    passed_count = sum(1 for _, ok, _, _ in results if ok)
    total = len(results)
    print("=" * 64)
    print(f"结果: {passed_count}/{total} 通过")
    print("=" * 64)
    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

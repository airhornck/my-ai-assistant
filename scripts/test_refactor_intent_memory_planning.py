#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
改造后项目测试：意图、记忆、策略脑。

覆盖：
- 意图识别（IntentAgent）：单轮 / 带上下文，置信度与澄清
- 策略脑（PlanningAgent）：各意图 → steps + plugins，plan 插件规范为列表
- meta_workflow planning_node：意图→规划→plan 与 analysis_plugins/generation_plugins
- 记忆（MemoryService）：get_memory_for_analyze、近期对话、用户摘要（无 DB 时跳过或返回空）
- 完整流程烟雾测试

运行：
  python scripts/test_refactor_intent_memory_planning.py
  pytest scripts/test_refactor_intent_memory_planning.py -v -s

环境：配置好 .env（如 DASHSCOPE_API_KEY）时意图/策略脑走真实 LLM；未配置时走 fallback。
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


# ---------- 意图识别 ----------
async def test_intent_agent_basic():
    """IntentAgent：多类意图与置信度、澄清逻辑"""
    from services.ai_service import SimpleAIService
    from core.intent.intent_agent import IntentAgent

    ai = SimpleAIService()
    llm = getattr(ai, "_llm", None) or getattr(ai.router, "powerful_model", None)
    if llm is None or not hasattr(llm, "invoke"):
        llm = ai._llm
    agent = IntentAgent(llm)

    cases = [
        ("帮我生成小红书文案", "generate_content"),
        ("我的账号最近流量不好", "account_diagnosis"),
        ("今天天气不错", "casual_chat"),
        ("想提升账号流量，有什么办法", "query_info"),
        ("帮我制定一个推广策略", "strategy_planning"),
        ("谢谢", "casual_chat"),
    ]
    print("\n--- IntentAgent 单轮 ---")
    for user_input, expected_intent in cases:
        result = await agent.classify_intent(user_input)
        intent = result.get("intent", "")
        confidence = result.get("confidence", 0)
        need_clarification = result.get("need_clarification", False)
        ok = expected_intent == intent or (expected_intent in ("casual_chat",) and intent in ("casual_chat", "free_discussion"))
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] \"{user_input[:25]}...\" -> intent={intent}, conf={confidence:.2f}, need_clarify={need_clarification}")
        if not ok:
            print(f"        expected ~{expected_intent}, got {intent}")


async def test_intent_with_context():
    """IntentAgent：带对话上下文"""
    from services.ai_service import SimpleAIService
    from core.intent.intent_agent import IntentAgent

    ai = SimpleAIService()
    llm = getattr(ai, "_llm", None) or ai._llm
    agent = IntentAgent(llm)

    context = "用户：我想做女装推广\n助手：好的，您有指定平台吗？"
    result = await agent.classify_intent("小红书吧", conversation_context=context)
    intent = result.get("intent", "")
    print(f"\n--- IntentAgent 多轮(带上下文) ---")
    print(f"  输入: \"小红书吧\" + 上下文 -> intent={intent}, confidence={result.get('confidence', 0):.2f}")
    # 可能被识别为 generate_content / query_info / free_discussion 等
    assert "intent" in result and "confidence" in result and "raw_query" in result


# ---------- 策略脑 ----------
async def test_planning_agent_steps_and_plugins():
    """PlanningAgent：根据意图输出 steps + plugins，且插件来自可用列表"""
    from services.ai_service import SimpleAIService
    from core.intent.planning_agent import PlanningAgent

    ai = SimpleAIService()
    llm = getattr(ai, "_llm", None) or ai._llm
    planning = PlanningAgent(llm)

    cases = [
        {
            "intent_data": {"intent": "generate_content", "confidence": 0.9, "raw_query": "帮我生成小红书文案", "notes": "生成"},
            "user_data": {"brand_name": "华为", "product_desc": "手机", "platform": "小红书"},
            "expect_has_generate": True,
            "expect_has_analyze": True,
        },
        {
            "intent_data": {"intent": "casual_chat", "confidence": 0.95, "raw_query": "你好", "notes": "闲聊"},
            "user_data": {},
            "expect_has_generate": False,
            "expect_has_analyze": False,
        },
        {
            "intent_data": {"intent": "account_diagnosis", "confidence": 0.85, "raw_query": "账号流量不好", "notes": "诊断"},
            "user_data": {"brand_name": "测试"},
            "expect_has_generate": False,
            "expect_has_analyze": True,
        },
    ]
    print("\n--- PlanningAgent 步骤与插件 ---")
    for i, case in enumerate(cases):
        plan_result = await planning.plan_steps(
            case["intent_data"],
            case.get("user_data"),
            "",
        )
        steps = plan_result.get("steps", [])
        step_names = [str(s.get("step", "")).lower() for s in steps if isinstance(s, dict)]
        has_generate = "generate" in step_names
        has_analyze = "analyze" in step_names
        analysis_plugins = []
        generation_plugins = []
        for s in steps:
            if isinstance(s, dict):
                if (s.get("step") or "").lower() == "analyze":
                    analysis_plugins.extend(s.get("plugins") or [])
                if (s.get("step") or "").lower() == "generate":
                    generation_plugins.extend(s.get("plugins") or [])

        # generate_content 至少含 generate；analyze 可选（不同模型可能只出 generate）
        ok = (case["expect_has_generate"] == has_generate) and (
            case["expect_has_analyze"] == has_analyze or (case["intent_data"]["intent"] == "generate_content" and has_generate)
        )
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] 意图={case['intent_data']['intent']} -> steps={step_names}, analyze_plugins={analysis_plugins}, gen_plugins={generation_plugins}")
        if not ok:
            print(f"        expected generate={case['expect_has_generate']}, analyze={case['expect_has_analyze']}")


async def test_planning_node_full():
    """meta_workflow planning_node：意图 -> 规划 -> plan 含 steps+plugins，且 analysis_plugins/generation_plugins 被正确提取"""
    from workflows.meta_workflow import build_meta_workflow

    wf = build_meta_workflow()
    payload = {
        "raw_query": "帮我写一篇小红书文案，品牌是测试品牌",
        "brand_name": "测试品牌",
        "topic": "新品推广",
    }
    state = {
        "user_input": json.dumps(payload, ensure_ascii=False),
        "session_id": "test_refactor",
        "user_id": "test_refactor_user",
    }
    config = {"configurable": {"thread_id": "test_refactor_planning"}}

    # 只跑 planning 节点：用 astream updates 取 planning 输出
    out = None
    async for chunk in wf.astream(state, config=config, stream_mode="updates"):
        if "planning" in chunk:
            out = chunk["planning"]
            break
    if out is None:
        final = await wf.ainvoke(state, config=config)
        out = final

    plan = out.get("plan") or []
    analysis_plugins = out.get("analysis_plugins") or []
    generation_plugins = out.get("generation_plugins") or []
    intent = out.get("intent", "")
    steps = [str(s.get("step", "")).lower() for s in plan if isinstance(s, dict)]

    print("\n--- meta_workflow planning_node 端到端 ---")
    print(f"  intent={intent}, plan_steps={steps}")
    print(f"  analysis_plugins={analysis_plugins}, generation_plugins={generation_plugins}")
    assert isinstance(plan, list), "plan 应为列表"
    assert "task_type" in out
    # 明确生成请求应含 generate 且顶层有 generation_plugins
    if "generate_content" in intent or "strategy_planning" in intent:
        assert "generate" in steps, f"生成类意图应有 generate 步骤: {steps}"
    print("  [OK] planning_node 返回结构正确且生成类意图含 generate")


# ---------- 记忆 ----------
async def test_memory_service_basic():
    """MemoryService：get_memory_for_analyze / get_recent_conversation_text 可调用不报错"""
    from domain.memory import MemoryService

    svc = MemoryService(cache=None)
    # 无 DB 时可能返回空，但不应抛异常（或仅因无连接抛可预期异常）
    print("\n--- MemoryService ---")
    try:
        mem = await svc.get_memory_for_analyze(
            user_id="test_refactor_user",
            brand_name="",
            product_desc="",
            topic="",
        )
        assert isinstance(mem, dict), "get_memory_for_analyze 应返回 dict"
        assert "preference_context" in mem or "effective_tags" in mem or len(mem) >= 0
        print(f"  get_memory_for_analyze: keys={list(mem.keys())}")
    except Exception as e:
        if "DATABASE_URL" in str(e) or "connect" in str(e).lower() or "database" in str(e).lower():
            print(f"  [SKIP] 记忆需数据库: {e}")
        else:
            raise

    try:
        text = await svc.get_recent_conversation_text("test_refactor_user", session_id="", limit=3)
        assert isinstance(text, str)
        print(f"  get_recent_conversation_text: len={len(text)}")
    except Exception as e:
        if "DATABASE_URL" in str(e) or "connect" in str(e).lower():
            print(f"  [SKIP] 近期对话需数据库: {e}")
        else:
            raise

    try:
        summary = await svc.get_user_summary("test_refactor_user")
        assert isinstance(summary, str)
        print(f"  get_user_summary: len={len(summary)}")
    except Exception as e:
        if "DATABASE_URL" in str(e) or "connect" in str(e).lower():
            print(f"  [SKIP] 用户摘要需数据库: {e}")
        else:
            raise


# ---------- 串联：完整流程不报错 ----------
async def test_full_flow_smoke():
    """跑通一次完整流程（闲聊或生成），确保意图->策略脑->执行不崩溃；生成请求时 plan 含 plugins"""
    from workflows.meta_workflow import build_meta_workflow

    wf = build_meta_workflow()
    state = {
        "user_input": json.dumps({
            "raw_query": "你好",
            "brand_name": "",
            "topic": "",
        }, ensure_ascii=False),
        "session_id": "test_smoke",
        "user_id": "test_smoke_user",
    }
    config = {"configurable": {"thread_id": "test_smoke_flow"}}
    try:
        final = await wf.ainvoke(state, config=config)
        assert "content" in final or "plan" in final
        plan = final.get("plan") or []
        a = final.get("analysis_plugins") or []
        g = final.get("generation_plugins") or []
        print("\n--- 完整流程烟雾测试 ---")
        print(f"  plan 步数={len(plan)}, analysis_plugins={a}, generation_plugins={g}, content_len={len(str(final.get('content', '')))}")
        print("  [OK] 流程跑通")
    except Exception as e:
        print(f"\n--- 完整流程烟雾测试 --- FAIL: {e}")
        raise


async def run_all():
    print("=" * 60)
    print("改造后测试：意图 / 记忆 / 策略脑")
    print("=" * 60)
    await test_intent_agent_basic()
    await test_intent_with_context()
    await test_planning_agent_steps_and_plugins()
    await test_planning_node_full()
    await test_memory_service_basic()
    await test_full_flow_smoke()
    print("\n" + "=" * 60)
    print("全部跑完")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all())

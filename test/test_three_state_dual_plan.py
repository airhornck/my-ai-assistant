"""
三态流程 + 双 Plan 模式专项测试。

重点验证：
  1. 固定 Plan 是否正常进入（意图+上下文 → 正确 template_id 与步骤）
  2. 动态 Plan 是否可正常拼接（无固定匹配时 → PlanningAgent 生成步骤，plan_template_id=dynamic）
  3. 固定与动态 Plan 是否与执行阶段正常衔接（同一套 execute_one_step 逻辑）
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from plans import (
    PLAN_TEMPLATE_DYNAMIC,
    get_plan,
    resolve_template_id,
    TEMPLATE_ACCOUNT_BUILDING,
    TEMPLATE_CONTENT_MATRIX,
    TEMPLATE_IP_DIAGNOSIS,
)
from workflows import ip_build_flow
from workflows.types import (
    IP_BUILD_PHASE_EXECUTING,
    IP_BUILD_PHASE_PLANNED,
    IP_BUILD_PHASE_DONE,
)


# ---------- 1. 固定 Plan 是否正常进入 ----------


def test_fixed_plan_resolve_ip_diagnosis():
    """意图/话题命中时解析为 ip_diagnosis 固定模板。"""
    assert resolve_template_id("account_diagnosis", {"topic": "账号流量"}) == TEMPLATE_IP_DIAGNOSIS
    assert resolve_template_id("账号诊断", {"topic": "数据"}) == TEMPLATE_IP_DIAGNOSIS
    assert resolve_template_id("account_diagnosis", {"topic": "做小红书"}) == TEMPLATE_IP_DIAGNOSIS


def test_fixed_plan_resolve_account_building():
    """意图/话题命中时解析为 account_building 固定模板。"""
    assert resolve_template_id("打造个人IP", {"topic": "做小红书"}) == TEMPLATE_ACCOUNT_BUILDING
    assert resolve_template_id("generate_content", {"topic": "账号打造"}) == TEMPLATE_ACCOUNT_BUILDING


def test_fixed_plan_resolve_content_matrix():
    """意图/话题命中时解析为 content_matrix 固定模板。"""
    assert resolve_template_id("strategy_planning", {"topic": "内容矩阵"}) == TEMPLATE_CONTENT_MATRIX
    assert resolve_template_id("内容规划", {"topic": "选题"}) == TEMPLATE_CONTENT_MATRIX


def test_fixed_plan_get_steps_structure():
    """固定模板返回的步骤结构正确、可被执行层使用。"""
    for tid, expected_first_step in [
        (TEMPLATE_IP_DIAGNOSIS, "analyze"),
        (TEMPLATE_ACCOUNT_BUILDING, "memory_query"),
        (TEMPLATE_CONTENT_MATRIX, "memory_query"),
    ]:
        steps = get_plan(tid)
        assert steps is not None, f"get_plan({tid}) 应有步骤"
        assert len(steps) >= 1
        assert steps[0].get("step") == expected_first_step
        for s in steps:
            assert "step" in s and "reason" in s
            if "params" not in s:
                pass  # 执行层会补全


@pytest.mark.asyncio
async def test_fixed_plan_entry_ip_diagnosis_via_plan_once():
    """Plan 阶段：账号诊断意图 → 进入 ip_diagnosis 固定 Plan，不调用 PlanningAgent。"""
    state = {
        "ip_context": {"brand_name": "测试", "topic": "账号诊断"},
        "phase": IP_BUILD_PHASE_PLANNED,
    }
    intent_result = {"intent": "account_diagnosis", "raw_query": "帮我诊断账号"}

    class MockAgent:
        called = False

        async def plan_steps(self, *args, **kwargs):
            self.called = True
            return {"steps": [{"step": "casual_reply", "params": {}, "reason": "mock"}], "task_type": "other"}

    agent = MockAgent()
    out = await ip_build_flow.plan_once_node(state, agent, intent_result)

    assert not agent.called, "固定 Plan 命中时不应调用 PlanningAgent"
    assert out["phase"] == IP_BUILD_PHASE_EXECUTING
    assert out["plan_template_id"] == TEMPLATE_IP_DIAGNOSIS
    assert len(out["plan"]) == 2
    assert out["plan"][0]["step"] == "analyze"
    assert out["plan"][1]["step"] == "casual_reply"
    assert out["current_step"] == 0
    assert out["step_outputs"] == []


@pytest.mark.asyncio
async def test_fixed_plan_entry_account_building_via_plan_once():
    """Plan 阶段：打造/账号话题 → 进入 account_building 固定 Plan。"""
    state = {
        "ip_context": {"brand_name": "A", "topic": "做小红书"},
        "phase": IP_BUILD_PHASE_PLANNED,
    }
    intent_result = {"intent": "打造个人IP", "raw_query": "想打造个人IP"}

    class MockAgent:
        called = False

        async def plan_steps(self, *args, **kwargs):
            self.called = True
            return {"steps": [], "task_type": "other"}

    agent = MockAgent()
    out = await ip_build_flow.plan_once_node(state, agent, intent_result)

    assert not agent.called
    assert out["plan_template_id"] == TEMPLATE_ACCOUNT_BUILDING
    assert out["phase"] == IP_BUILD_PHASE_EXECUTING
    assert len(out["plan"]) >= 4  # memory_query, analyze, analyze, generate, evaluate


@pytest.mark.asyncio
async def test_fixed_plan_entry_content_matrix_via_plan_once():
    """Plan 阶段：内容/矩阵话题 → 进入 content_matrix 固定 Plan。"""
    state = {
        "ip_context": {"brand_name": "B", "topic": "内容矩阵"},
        "phase": IP_BUILD_PHASE_PLANNED,
    }
    intent_result = {"intent": "strategy_planning", "raw_query": "做内容矩阵"}

    class MockAgent:
        called = False

        async def plan_steps(self, *args, **kwargs):
            self.called = True
            return {"steps": [], "task_type": "other"}

    agent = MockAgent()
    out = await ip_build_flow.plan_once_node(state, agent, intent_result)

    assert not agent.called
    assert out["plan_template_id"] == TEMPLATE_CONTENT_MATRIX
    assert out["phase"] == IP_BUILD_PHASE_EXECUTING
    assert len(out["plan"]) >= 3


# ---------- 2. 动态 Plan 是否可正常拼接 ----------


@pytest.mark.asyncio
async def test_dynamic_plan_composition_no_fixed_match():
    """无固定模板匹配时调用 PlanningAgent，返回动态步骤，plan_template_id=dynamic。"""
    state = {
        "ip_context": {"brand_name": "C", "topic": "随便聊聊"},
        "phase": IP_BUILD_PHASE_PLANNED,
    }
    intent_result = {"intent": "casual_chat", "raw_query": "你好呀"}

    dynamic_steps = [
        {"step": "casual_reply", "plugins": [], "params": {"message": ""}, "reason": "友好回复"},
    ]

    class MockAgent:
        async def plan_steps(self, *args, **kwargs):
            return {"steps": dynamic_steps, "task_type": "campaign_or_copy"}

    agent = MockAgent()
    out = await ip_build_flow.plan_once_node(state, agent, intent_result)

    assert out["plan_template_id"] == PLAN_TEMPLATE_DYNAMIC
    assert out["phase"] == IP_BUILD_PHASE_EXECUTING
    assert out["plan"] == dynamic_steps
    assert out["current_step"] == 0
    assert out["step_outputs"] == []


@pytest.mark.asyncio
async def test_dynamic_plan_composition_multi_step():
    """动态 Plan 可包含多步（如 kb_retrieve + analyze + casual_reply）。"""
    state = {
        "ip_context": {"brand_name": "D", "topic": "专业方案"},
        "phase": IP_BUILD_PHASE_PLANNED,
    }
    intent_result = {"intent": "query_info", "raw_query": "给个专业方案"}

    dynamic_steps = [
        {"step": "kb_retrieve", "plugins": [], "params": {"query": ""}, "reason": "查知识库"},
        {"step": "analyze", "plugins": ["topic_selection_plugin"], "params": {}, "reason": "分析"},
        {"step": "casual_reply", "plugins": [], "params": {"message": ""}, "reason": "回复"},
    ]

    class MockAgent:
        async def plan_steps(self, *args, **kwargs):
            return {"steps": dynamic_steps, "task_type": "campaign_or_copy"}

    agent = MockAgent()
    out = await ip_build_flow.plan_once_node(state, agent, intent_result)

    assert out["plan_template_id"] == PLAN_TEMPLATE_DYNAMIC
    assert len(out["plan"]) == 3
    assert out["plan"][0]["step"] == "kb_retrieve"
    assert out["plan"][1]["step"] == "analyze"
    assert out["plan"][2]["step"] == "casual_reply"


# ---------- 3. 固定与动态 Plan 与执行阶段衔接 ----------


@pytest.mark.asyncio
async def test_execute_fixed_plan_two_steps_then_done():
    """固定 Plan（如 ip_diagnosis 两步）：执行两轮后 phase=done，content 为汇总。"""
    plan = [
        {"step": "analyze", "params": {}, "reason": "分析"},
        {"step": "casual_reply", "params": {"message": "完成"}, "reason": "回复"},
    ]
    state = {
        "plan": plan,
        "current_step": 0,
        "step_outputs": [],
        "ip_context": {"brand_name": "E", "topic": "诊断"},
        "user_input": "{}",
    }

    async def runner(base, step_config, ip_ctx, outputs):
        step_name = step_config.get("step", "")
        if step_name == "analyze":
            return {"step": "analyze", "reason": "分析", "result": {"reply": "诊断结果：账号健康"}}
        return {"step": "casual_reply", "reason": "回复", "result": {"reply": "方案已生成"}}

    out1 = await ip_build_flow.execute_one_step_node(state, runner)
    assert out1["phase"] == IP_BUILD_PHASE_EXECUTING
    assert out1["current_step"] == 1
    assert len(out1["step_outputs"]) == 1

    out2 = await ip_build_flow.execute_one_step_node(out1, runner)
    assert out2["phase"] == IP_BUILD_PHASE_DONE
    assert out2["current_step"] == 2
    assert len(out2["step_outputs"]) == 2
    assert "诊断结果" in (out2.get("content") or "")
    assert "方案已生成" in (out2.get("content") or "")


@pytest.mark.asyncio
async def test_execute_dynamic_plan_same_runner_path():
    """动态 Plan（单步 casual_reply）：与固定 Plan 走同一 execute_one_step_node，能正常完成。"""
    plan = [
        {"step": "casual_reply", "params": {"message": ""}, "reason": "友好回复"},
    ]
    state = {
        "plan": plan,
        "current_step": 0,
        "step_outputs": [],
        "ip_context": {},
        "user_input": "{}",
    }

    async def runner(base, step_config, ip_ctx, outputs):
        return {"step": "casual_reply", "reason": "友好回复", "result": {"reply": "你好，有什么可以帮您？"}}

    out = await ip_build_flow.execute_one_step_node(state, runner)
    assert out["phase"] == IP_BUILD_PHASE_DONE
    assert len(out["step_outputs"]) == 1
    assert "有什么可以帮您" in (out.get("content") or "")


@pytest.mark.asyncio
async def test_execute_dynamic_plan_multiple_steps():
    """动态 Plan 多步（与固定 Plan 一致的结构）：逐步执行至 done。"""
    plan = [
        {"step": "memory_query", "params": {}, "reason": "查偏好"},
        {"step": "casual_reply", "params": {"message": ""}, "reason": "回复"},
    ]
    state = {
        "plan": plan,
        "current_step": 0,
        "step_outputs": [],
        "ip_context": {"brand_name": "F", "topic": "T"},
        "user_input": "{}",
    }

    async def runner(base, step_config, ip_ctx, outputs):
        s = step_config.get("step", "")
        return {"step": s, "reason": step_config.get("reason"), "result": {"reply": f"步骤 {s} 完成"}}

    out1 = await ip_build_flow.execute_one_step_node(state, runner)
    assert out1["phase"] == IP_BUILD_PHASE_EXECUTING
    assert out1["current_step"] == 1

    out2 = await ip_build_flow.execute_one_step_node(out1, runner)
    assert out2["phase"] == IP_BUILD_PHASE_DONE
    assert "memory_query" in (out2.get("content") or "") and "casual_reply" in (out2.get("content") or "")


@pytest.mark.asyncio
async def test_execute_fixed_and_dynamic_use_same_runner_contract():
    """固定 Plan 与动态 Plan 的步骤均通过同一 runner(base, step_config, ip_ctx, outputs) 执行。"""
    # 固定风格：analyze + casual_reply
    fixed_style = [
        {"step": "analyze", "params": {}, "reason": "分析"},
        {"step": "casual_reply", "params": {"message": ""}, "reason": "回复"},
    ]
    # 动态风格：casual_reply 单步
    dynamic_style = [{"step": "casual_reply", "params": {"message": ""}, "reason": "回复"}]

    calls = []

    async def record_runner(base, step_config, ip_ctx, outputs):
        calls.append(step_config.get("step"))
        return {"step": step_config.get("step"), "reason": "", "result": {"reply": "ok"}}

    for plan, expected_steps in [(fixed_style, ["analyze", "casual_reply"]), (dynamic_style, ["casual_reply"])]:
        calls.clear()
        s = {
            "plan": plan,
            "current_step": 0,
            "step_outputs": [],
            "ip_context": {},
            "user_input": "{}",
        }
        for _ in range(len(plan) + 2):
            if s.get("phase") == IP_BUILD_PHASE_DONE:
                break
            s = await ip_build_flow.execute_one_step_node(s, record_runner)
        assert s.get("phase") == IP_BUILD_PHASE_DONE
        assert calls == expected_steps, f"plan 期望执行 {expected_steps}，实际 {calls}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

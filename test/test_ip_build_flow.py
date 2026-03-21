"""
IP 打造三态流程与双 Plan 模式测试。
验证：Intake 合并与必填检查、固定/动态 Plan、单步执行与缺参追问、中断处理、汇总输出。
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import json

from intake_guide import build_pending_questions, infer_fields, merge_context, missing_required
from plans import (
    get_fixed_plan,
    get_template_meta,
    list_template_ids,
    PLAN_TEMPLATE_DYNAMIC,
    resolve_template_id,
    TEMPLATE_ACCOUNT_BUILDING,
    TEMPLATE_CONTENT_MATRIX,
    TEMPLATE_IP_DIAGNOSIS,
)
from workflows import ip_build_flow
from workflows.types import (
    IP_BUILD_PHASE_INTAKE,
    IP_BUILD_PHASE_PLANNED,
    IP_BUILD_PHASE_EXECUTING,
    IP_BUILD_PHASE_DONE,
)


# ----- 纯函数（同步）-----
def test_infer_fields_account_and_brand():
    """infer：建账号、品牌叫/品牌名叫、流量诊断、矩阵选题。"""
    r1 = infer_fields("我打算在B站上建一个账号")
    assert "账号" in (r1.get("topic") or "")
    r2 = infer_fields("品牌叫小红果")
    assert r2.get("brand_name") == "小红果"
    r3 = infer_fields("品牌名叫青禾矩阵")
    assert r3.get("brand_name") == "青禾矩阵"
    r4 = infer_fields("我B站账号最近流量很差，帮我看看")
    assert "流量" in (r4.get("topic") or "") or "诊断" in (r4.get("topic") or "")
    r5 = infer_fields("我想做小红书内容矩阵和选题规划")
    assert "矩阵" in (r5.get("topic") or "") or "选题" in (r5.get("topic") or "")


def test_merge_ip_context():
    """合并 ip_context 不覆盖已有非空值（intake_guide）。"""
    merged = merge_context(
        {"brand_name": "已有品牌", "topic": ""},
        {"brand_name": "新品牌", "topic": "做小红书"},
    )
    assert merged["brand_name"] == "已有品牌"
    assert merged["topic"] == "做小红书"


def test_missing_required_keys():
    """必填缺失检测（intake_guide）。"""
    assert missing_required({}) == ["brand_name", "topic"]
    assert missing_required({"brand_name": "A", "topic": "B"}) == []
    assert missing_required({"brand_name": "A"}) == ["topic"]


def test_build_pending_questions():
    """生成 1～3 个友好问题，含选项与 optional（intake_guide）。"""
    qs = build_pending_questions(["brand_name", "topic"])
    assert len(qs) == 2
    assert any(q.get("key") == "brand_name" for q in qs)
    assert any(q.get("options") for q in qs)  # topic 有 options
    qs_opt = build_pending_questions(["product_desc"])
    assert len(qs_opt) == 1 and qs_opt[0].get("optional") is True


def test_resolve_template_id():
    """模板 ID 解析：固定模板与 dynamic。"""
    assert resolve_template_id("account_diagnosis", {"topic": "账号流量"}) == TEMPLATE_IP_DIAGNOSIS
    assert resolve_template_id("账号诊断", {"topic": "数据"}) == TEMPLATE_IP_DIAGNOSIS
    assert resolve_template_id("打造个人IP", {"topic": "做小红书"}) == TEMPLATE_ACCOUNT_BUILDING
    assert resolve_template_id("strategy_planning", {"topic": "内容矩阵"}) == TEMPLATE_CONTENT_MATRIX
    assert resolve_template_id("casual_chat", {}) == PLAN_TEMPLATE_DYNAMIC


def test_fixed_plan_templates():
    """固定 Plan 模板存在且结构正确。"""
    ids = list_template_ids()
    assert TEMPLATE_IP_DIAGNOSIS in ids
    assert TEMPLATE_CONTENT_MATRIX in ids
    plan = get_fixed_plan(TEMPLATE_IP_DIAGNOSIS)
    assert plan is not None and len(plan) >= 1
    assert plan[0].get("step") == "analyze"
    assert "reason" in plan[0]
    meta_ab = get_template_meta(TEMPLATE_ACCOUNT_BUILDING)
    assert meta_ab and meta_ab.get("name") == "账号打造"
    meta_ip = get_template_meta(TEMPLATE_IP_DIAGNOSIS)
    assert meta_ip and meta_ip.get("name") == "IP/账号诊断"


def test_fill_step_params():
    """填充步骤参数，generate 缺 platform 时 missing 非空。"""
    step_gen = {"step": "generate", "params": {}}
    params, missing = ip_build_flow._fill_step_params(step_gen, {"brand_name": "A", "topic": "B"}, [], {})
    assert "platform" in missing
    step_gen2 = {"step": "generate", "params": {"platform": "小红书"}}
    params2, missing2 = ip_build_flow._fill_step_params(step_gen2, {}, [], {})
    assert "platform" not in missing2
    step_mem = {"step": "memory_query", "params": {}}
    p, m = ip_build_flow._fill_step_params(step_mem, {"topic": "T"}, [], {})
    assert not m


def test_detect_execute_interrupt():
    """执行阶段用户中断：继续/放弃/重规划。"""
    assert ip_build_flow._detect_execute_interrupt({}, "我们放弃吧") == "abort"
    assert ip_build_flow._detect_execute_interrupt({}, "重新规划") == "replan"
    assert ip_build_flow._detect_execute_interrupt({}, "继续执行") == "continue"
    assert ip_build_flow._detect_execute_interrupt({}, "帮我生成文案") is None


def test_compile_step_outputs():
    """合并 step_outputs 为最终文案。"""
    out = ip_build_flow._compile_step_outputs([
        {"step": "analyze", "result": {"reply": "分析完成"}},
        {"step": "generate", "result": {"content": "生成的文案"}},
    ])
    assert "分析完成" in out and "生成的文案" in out
    assert ip_build_flow._compile_step_outputs([]) == "（暂无输出）"


# ----- 异步节点（mock LLM / runner）-----
@pytest.mark.asyncio
async def test_intake_node_missing():
    """Intake：有缺失时返回 phase=intake 与 pending_questions。"""
    state = {"ip_context": {}, "phase": IP_BUILD_PHASE_INTAKE}
    intent_result = {"intent": "generate_content", "confidence": 0.9}
    extracted = {"brand_name": "测试品牌"}
    out = await ip_build_flow.intake_node(state, intent_result, extracted, llm=None)
    assert out["phase"] == IP_BUILD_PHASE_INTAKE
    assert len(out["pending_questions"]) >= 1
    assert out["ip_context"]["brand_name"] == "测试品牌"


@pytest.mark.asyncio
async def test_intake_node_threshold_met():
    """Intake：必填齐时返回 phase=planned，无 pending_questions。"""
    state = {"ip_context": {"brand_name": "A", "topic": "做小红书"}, "phase": IP_BUILD_PHASE_INTAKE}
    intent_result = {"intent": "generate_content"}
    extracted = {}
    out = await ip_build_flow.intake_node(state, intent_result, extracted, llm=None)
    assert out["phase"] == IP_BUILD_PHASE_PLANNED
    assert out["pending_questions"] == []


@pytest.mark.asyncio
async def test_intake_second_turn_updates_topic_and_stops_reasking_brand_name():
    """
    回归：第二轮用户明确说“还没有账号、想打造账号”，应能更新 topic（避免沿用上一轮推广话题），
    并自动填入 brand_name 占位，避免重复追问 brand_name。
    """
    # 第一轮：推广产品 → 进入 intake，缺 brand_name
    state = {"ip_context": {}, "phase": IP_BUILD_PHASE_INTAKE}
    intent_result = {"intent": "free_discussion"}
    out1 = await ip_build_flow.intake_node(
        state,
        intent_result,
        {"_raw_query": "我想推广产品"},
        llm=None,
    )
    assert out1["phase"] == IP_BUILD_PHASE_INTAKE
    assert any(q.get("key") == "brand_name" for q in out1.get("pending_questions") or [])
    assert (out1.get("ip_context") or {}).get("topic") in ("产品推广", "我想推广产品")

    # 第二轮：用户说没有账号、想打造账号（应覆盖 topic，并填 brand_name 占位）
    out2 = await ip_build_flow.intake_node(
        {**out1, "phase": IP_BUILD_PHASE_INTAKE},
        {"intent": "free_discussion"},
        {"_raw_query": "我是个体商户，我是做教育的，目前还没有自己的账号，我想打造一个账号"},
        llm=None,
    )
    ctx2 = out2.get("ip_context") or {}
    assert "账号打造" in (ctx2.get("topic") or "")
    assert (ctx2.get("brand_name") or "").strip()  # 已填占位
    assert not any(q.get("key") == "brand_name" for q in out2.get("pending_questions") or [])


@pytest.mark.asyncio
async def test_plan_once_node_fixed():
    """Plan 阶段：固定模板写入 plan，phase=executing，current_step=0。"""
    state = {"ip_context": {"brand_name": "A", "topic": "账号诊断"}, "phase": IP_BUILD_PHASE_PLANNED}
    intent_result = {"intent": "account_diagnosis", "raw_query": "帮我诊断账号"}
    class MockPlanningAgent:
        async def plan_steps(self, *args, **kwargs):
            return {"steps": [], "task_type": "campaign_or_copy"}
    agent = MockPlanningAgent()
    out = await ip_build_flow.plan_once_node(state, agent, intent_result)
    assert out["phase"] == IP_BUILD_PHASE_EXECUTING
    assert out["current_step"] == 0
    assert out["step_outputs"] == []
    assert len(out["plan"]) >= 1
    assert out.get("plan_template_id") in (TEMPLATE_IP_DIAGNOSIS, TEMPLATE_ACCOUNT_BUILDING, PLAN_TEMPLATE_DYNAMIC)


@pytest.mark.asyncio
async def test_execute_one_step_missing_params():
    """执行阶段：缺参时返回 pending_questions，不调用 runner。"""
    state = {
        "plan": [{"step": "generate", "params": {}, "reason": "生成"}],
        "current_step": 0,
        "step_outputs": [],
        "ip_context": {"brand_name": "A", "topic": "B"},
        "user_input": "{}",
    }
    async def _no_call(*args, **kwargs):
        raise AssertionError("should not be called")
    out = await ip_build_flow.execute_one_step_node(state, _no_call)
    assert out["phase"] == IP_BUILD_PHASE_EXECUTING
    assert len(out["pending_questions"]) >= 1
    assert out["current_step"] == 0
    assert out["step_outputs"] == []


@pytest.mark.asyncio
async def test_execute_one_step_success():
    """执行阶段：参数齐时调用 runner，step_outputs 增加，current_step+1。"""
    state = {
        "plan": [
            {"step": "memory_query", "params": {}, "reason": "记忆"},
            {"step": "analyze", "params": {}, "reason": "分析"},
        ],
        "current_step": 0,
        "step_outputs": [],
        "ip_context": {"brand_name": "A", "topic": "B"},
        "user_id": "u1",
        "user_input": "{}",
    }
    async def _runner(base, step_config, ip_ctx, outputs):
        return {"step": step_config["step"], "reason": step_config.get("reason"), "result": {"has_memory": True}}
    out = await ip_build_flow.execute_one_step_node(state, _runner)
    assert out["phase"] == IP_BUILD_PHASE_EXECUTING
    assert out["current_step"] == 1
    assert len(out["step_outputs"]) == 1
    assert out["step_outputs"][0]["step"] == "memory_query"


@pytest.mark.asyncio
async def test_execute_one_step_last_step_done():
    """执行阶段：最后一步完成后 phase=done，content 为汇总。"""
    state = {
        "plan": [{"step": "casual_reply", "params": {"message": "完成"}, "reason": "回复"}],
        "current_step": 0,
        "step_outputs": [],
        "ip_context": {},
        "user_input": "{}",
    }
    async def _runner(base, step_config, ip_ctx, outputs):
        return {"step": "casual_reply", "reason": "回复", "result": {"reply": "方案已生成"}}
    out = await ip_build_flow.execute_one_step_node(state, _runner)
    assert out["phase"] == IP_BUILD_PHASE_DONE
    assert "方案已生成" in (out.get("content") or "")


@pytest.mark.asyncio
async def test_execute_interrupt_abort():
    """执行阶段：用户说放弃 → phase=done，content 提示已放弃。"""
    state = {
        "plan": [{"step": "analyze", "params": {}, "reason": "分析"}],
        "current_step": 0,
        "step_outputs": [],
        "ip_context": {},
        "user_input": json.dumps({"raw_query": "算了不做了放弃"}),
    }
    async def _no_call(*args, **kwargs):
        raise AssertionError("should not run step")
    out = await ip_build_flow.execute_one_step_node(state, _no_call)
    assert out["phase"] == IP_BUILD_PHASE_DONE
    assert "放弃" in (out.get("content") or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
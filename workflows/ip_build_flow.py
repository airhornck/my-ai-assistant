"""
IP 打造三态流程：Intake（引导收集）→ Planned（一次生成 Plan）→ Execute（单步执行 + 缺参追问）→ Done（汇总输出）。
双 Plan 模式：固定模板 或 LLM 动态 Plan。每轮只执行一个 step，参数不足时生成 pending_questions 暂停。

会话约定：调用方在请求前从 session.initial_data 合并 phase、ip_context、plan、current_step、step_outputs 到 state；
请求后将 state 中上述字段及 pending_questions、content 写回 session，以便下一轮延续。
启动 IP 流程：在创建会话或首轮请求时设置 initial_data.phase = "intake", initial_data.ip_context = {}。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from workflows.types import (
    IP_BUILD_PHASE_DONE,
    IP_BUILD_PHASE_INTAKE,
    IP_BUILD_PHASE_EXECUTING,
    IP_BUILD_PHASE_PLANNED,
)

from intake_guide import (
    build_pending_questions,
    infer_fields,
    merge_context,
    missing_required,
)
from plans import (
    PLAN_TEMPLATE_DYNAMIC,
    apply_clear_template_lock_to_ip_context,
    get_plan,
    get_template_meta,
    resolve_template_id,
)

logger = logging.getLogger(__name__)


async def intake_node(
    state: dict,
    intent_result: dict,
    extracted_fields: dict,
    llm: Any,
) -> dict:
    """
    Intake 节点：合并 ip_context，检查必填，生成 pending_questions 或标记可进入 Plan。
    不执行策略规划；仅做意图解析 + 字段抽取 + 友好提问。
    """
    base = state.copy()
    raw_query = (extracted_fields or {}).get("_raw_query") or ""
    extracted_clean = dict(extracted_fields or {})
    extracted_clean.pop("_raw_query", None)
    inferred = infer_fields(str(raw_query), existing_ip_context=base.get("ip_context") or {})
    # Intake 阶段：允许用推断结果更新 topic（用户可能改变方向），避免被上一轮 topic 锁死
    ip_context = merge_context(base.get("ip_context") or {}, inferred, overwrite_keys=("topic",))
    ip_context = merge_context(ip_context, extracted_clean, overwrite_keys=("topic",))
    ip_context = apply_clear_template_lock_to_ip_context(ip_context)
    missing = missing_required(ip_context)
    intent = intent_result.get("intent", "free_discussion")

    if not missing:
        # 必填已齐，进入 Plan 阶段（由上层在下一轮调用 plan_once_node）
        return {
            **base,
            "ip_context": ip_context,
            "phase": IP_BUILD_PHASE_PLANNED,
            "pending_questions": [],
            "intent": intent,
        }
    # 用户友好引导：每轮 1～3 个关键问题，选项化 + 可跳过
    pending_questions = build_pending_questions(missing, intent, max_questions=3)
    return {
        **base,
        "ip_context": ip_context,
        "phase": IP_BUILD_PHASE_INTAKE,
        "pending_questions": pending_questions,
        "intent": intent,
    }


async def plan_once_node(
    state: dict,
    planning_agent: Any,
    intent_result: dict,
) -> dict:
    """
    Plan 阶段（只执行一次）：固定模板 或 LLM 动态 Plan，写入 state，phase=executing，current_step=0。
    """
    base = state.copy()
    ip_context = apply_clear_template_lock_to_ip_context(dict(base.get("ip_context") or {}))
    intent = intent_result.get("intent", "free_discussion")

    # 统一按模板 ID 引用：固定模板由 registry 解析，无匹配则为 dynamic
    template_id = resolve_template_id(intent, ip_context)
    plan = get_plan(template_id) if template_id else None
    if plan:
        # 兼容格式：补全 params
        for s in plan:
            if "params" not in s:
                s["params"] = {}
        meta = get_template_meta(template_id) or {}
        plan_name = (meta.get("name") or template_id or "").strip()
        new_ip = dict(ip_context)
        new_ip["locked_template_id"] = template_id
        return {
            **base,
            "ip_context": new_ip,
            "plan": plan,
            "plan_template_id": template_id,
            "plan_template_name": plan_name,
            "phase": IP_BUILD_PHASE_EXECUTING,
            "current_step": 0,
            "step_outputs": [],
            "pending_questions": [],
            "task_type": "ip_build",
        }
    # 动态 Plan（template_id=dynamic）：调用 PlanningAgent 一次
    user_data = {
        "brand_name": ip_context.get("brand_name", ""),
        "product_desc": ip_context.get("product_desc", ""),
        "topic": ip_context.get("topic", ""),
        "platform": ip_context.get("platform", ""),
    }
    plan_result = await planning_agent.plan_steps(
        intent_data=intent_result,
        user_data=user_data,
        conversation_context="",
    )
    steps = plan_result.get("steps", [])
    for s in steps:
        if "params" not in s:
            s["params"] = {}
    new_ip = dict(ip_context)
    new_ip.pop("locked_template_id", None)
    new_ip.pop("plan_template_lock", None)
    return {
        **base,
        "ip_context": new_ip,
        "plan": steps,
        "plan_template_id": PLAN_TEMPLATE_DYNAMIC,
        "plan_template_name": "动态规划",
        "phase": IP_BUILD_PHASE_EXECUTING,
        "current_step": 0,
        "step_outputs": [],
        "pending_questions": [],
        "task_type": plan_result.get("task_type", "campaign_or_copy"),
    }


def _fill_step_params(step: dict, ip_context: dict, step_outputs: list, user_input_data: dict) -> tuple[dict, list[str]]:
    """
    用 ip_context + step_outputs + user_input_data 填充当前步骤 params。
    返回 (filled_params, missing_param_keys)。
    """
    params = dict(step.get("params") or {})
    missing = []
    step_name = (step.get("step") or "").lower()
    brand = ip_context.get("brand_name") or user_input_data.get("brand_name") or ""
    product = ip_context.get("product_desc") or user_input_data.get("product_desc") or ""
    topic = ip_context.get("topic") or user_input_data.get("topic") or ""
    platform = ip_context.get("platform") or user_input_data.get("platform") or ""
    fallback_query = f"{brand} {product} {topic}".strip()

    if step_name == "web_search" and not (params.get("query") or "").strip():
        params["query"] = fallback_query or (user_input_data.get("raw_query") or "")
    if step_name == "generate":
        if not (params.get("platform") or "").strip() and platform:
            params["platform"] = platform
        if not (params.get("platform") or "").strip():
            missing.append("platform")
    if step_name == "kb_retrieve" and not (params.get("query") or "").strip():
        params["query"] = fallback_query or "营销策略"
    return params, missing


def _detect_execute_interrupt(user_input_data: dict, raw_query: str) -> str | None:
    """检测执行阶段用户中断意图：继续 / 放弃 / 重规划。返回 'continue' | 'abort' | 'replan' | None。"""
    raw = (raw_query or "").strip().lower()
    if not raw:
        return None
    if any(k in raw for k in ("继续", "接着", "下一步", "继续执行")):
        return "continue"
    if any(k in raw for k in ("放弃", "取消", "不做了", "终止")):
        return "abort"
    if any(k in raw for k in ("重规划", "重新规划", "换一个方案", "重新来")):
        return "replan"
    return None


async def execute_one_step_node(
    state: dict,
    step_runner: Any,
) -> dict:
    """
    执行阶段：每轮只执行一个 step。
    若当前 step 参数不足，生成 pending_questions 并返回（不执行插件）；
    否则执行 step，将结果写入 step_outputs，current_step += 1；若 Plan 完成则 phase=done。
    支持用户中断：继续 / 放弃 / 重规划。
    """
    base = state.copy()
    plan = base.get("plan") or []
    current_step = int(base.get("current_step") or 0)
    step_outputs = list(base.get("step_outputs") or [])
    ip_context = base.get("ip_context") or {}
    user_input_str = base.get("user_input") or ""
    try:
        user_input_data = json.loads(user_input_str) if isinstance(user_input_str, str) else {}
    except (TypeError, json.JSONDecodeError):
        user_input_data = {}
    raw_query = (user_input_data.get("raw_query") or user_input_str or "").strip()

    # 用户中断：放弃 → phase=done，content 提示已放弃；重规划 → 清空 plan，phase=planned
    interrupt = _detect_execute_interrupt(user_input_data, raw_query)
    if interrupt == "abort":
        return {
            **base,
            "phase": IP_BUILD_PHASE_DONE,
            "content": "已按您的要求放弃本次执行。如需重新开始，可发起新对话或选择「重规划」。",
            "step_outputs": step_outputs,
            "pending_questions": [],
        }
    if interrupt == "replan":
        return {
            **base,
            "phase": IP_BUILD_PHASE_PLANNED,
            "plan": [],
            "current_step": 0,
            "step_outputs": [],
            "pending_questions": [{"key": "_replan", "question": "已清空当前计划，下一轮将根据您的意图重新生成方案。请直接说明新需求。", "options": [], "optional": True}],
        }
    # continue 或 None：正常执行当前步

    # 上轮本步失败后的追问（key=_error）：解析「重试 / 跳过」，避免用户回复「好的」时反复踩同一异常
    pending_before = list(base.get("pending_questions") or [])
    has_error_pending = any(isinstance(q, dict) and q.get("key") == "_error" for q in pending_before)
    if has_error_pending:
        rq = (raw_query or "").strip()
        skip_err = any(k in rq for k in ("跳过", "不试了", "算了", "不要了"))
        retry_err = any(k in rq for k in ("重试", "再试", "继续执行")) or rq in (
            "好的",
            "好",
            "嗯",
            "可以",
            "行的",
            "继续",
            "再来",
        )
        if skip_err and current_step < len(plan):
            step_config_err = plan[current_step]
            step_nm = (step_config_err.get("step") or "unknown").lower()
            out_skip = {
                "step": step_nm,
                "reason": step_config_err.get("reason", ""),
                "result": {"skipped": "user_skip_after_error"},
            }
            new_outputs = step_outputs + [out_skip]
            next_idx = current_step + 1
            if next_idx >= len(plan):
                return {
                    **base,
                    "phase": IP_BUILD_PHASE_DONE,
                    "current_step": next_idx,
                    "step_outputs": new_outputs,
                    "content": _compile_step_outputs(new_outputs),
                    "pending_questions": [],
                }
            return {
                **base,
                "phase": IP_BUILD_PHASE_EXECUTING,
                "current_step": next_idx,
                "step_outputs": new_outputs,
                "pending_questions": [],
            }
        if retry_err:
            base = {**base, "pending_questions": []}
            step_outputs = list(base.get("step_outputs") or [])
        else:
            return {
                **base,
                "phase": IP_BUILD_PHASE_EXECUTING,
                "pending_questions": pending_before,
                "current_step": current_step,
                "step_outputs": step_outputs,
                "content": "本步曾执行失败。请回复「重试」再试一次，或「跳过」进入下一步。",
            }

    if current_step >= len(plan):
        return {
            **base,
            "phase": IP_BUILD_PHASE_DONE,
            "content": _compile_step_outputs(step_outputs),
        }

    step_config = plan[current_step]
    filled_params, missing = _fill_step_params(step_config, ip_context, step_outputs, user_input_data)
    if missing:
        pending_questions = [{"key": k, "question": f"请补充本步所需：{k}", "options": [], "optional": False} for k in missing[:3]]
        if "platform" in missing:
            pending_questions = [{"key": "platform", "question": "请选择或填写主要发布平台（如 B站、小红书、抖音）", "options": ["B站", "小红书", "抖音", "视频号"], "optional": False}]
        return {
            **base,
            "phase": IP_BUILD_PHASE_EXECUTING,
            "pending_questions": pending_questions,
            "current_step": current_step,
            "step_outputs": step_outputs,
        }

    # 执行单步：step_runner(state, step_config, filled_params) -> step_output dict
    step_config_filled = {**step_config, "params": filled_params}
    try:
        out = await step_runner(base, step_config_filled, ip_context, step_outputs)
    except Exception as e:
        logger.warning("execute_one_step 执行失败: %s", e, exc_info=True)
        return {
            **base,
            "phase": IP_BUILD_PHASE_EXECUTING,
            "pending_questions": [{"key": "_error", "question": f"本步执行出错，是否重试？({str(e)[:50]})", "options": ["重试", "跳过"], "optional": True}],
            "current_step": current_step,
            "step_outputs": step_outputs,
        }
    step_outputs = step_outputs + [out]
    next_idx = current_step + 1
    if next_idx >= len(plan):
        return {
            **base,
            "phase": IP_BUILD_PHASE_DONE,
            "current_step": next_idx,
            "step_outputs": step_outputs,
            "content": _compile_step_outputs(step_outputs),
        }
    return {
        **base,
        "phase": IP_BUILD_PHASE_EXECUTING,
        "current_step": next_idx,
        "step_outputs": step_outputs,
        "pending_questions": [],
    }


def _compile_step_outputs(step_outputs: list) -> str:
    """合并 step_outputs 为最终输出文案。"""
    parts = []
    for o in step_outputs:
        step_name = o.get("step", "")
        result = o.get("result", {})
        if not isinstance(result, dict):
            if isinstance(result, str) and result.strip():
                parts.append(f"【{step_name}】\n{result}")
            continue
        reply = result.get("reply") or result.get("summary") or result.get("content")
        if reply:
            parts.append(f"【{step_name}】\n{reply}")
        elif result.get("suggestions") is not None or result.get("overall_score") is not None:
            score = result.get("overall_score", 0)
            sugg = result.get("suggestions", "")
            parts.append(f"【{step_name}】\n综合分：{score}\n{sugg}".strip())
        elif result.get("account_diagnosis"):
            diag = result["account_diagnosis"]
            parts.append(f"【{step_name}】\n{diag if isinstance(diag, str) else str(diag)}")
        elif result.get("angle"):
            parts.append(f"【{step_name}】\n{result.get('angle', '')}")
    return "\n\n".join(parts).strip() if parts else "（暂无输出）"

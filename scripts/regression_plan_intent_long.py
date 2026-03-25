#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
长对话回归：闲聊 / 固定 Plan / 动态 Plan / 切换 / 打断退出。

每轮记录：
- InputProcessor（细粒度意图 + structured_data + explicit_content_request）
- IntentAgent（粗粒度意图，与 meta / ip_build 一致）
- resolve_template_id + 固定模板步骤摘要或动态 PlanningAgent 步骤
- skill_runtime：首个 analyze 步的插件展开与 ab_bucket（固定或动态计划）
- trace_id：与 meta_workflow 同格式 `{session[:24]}-{uuid10}`
- conversation_context：传入 InputProcessor / IntentAgent 的完整上下文字符串
- trace_events：与线上一致的伪 trace 节点序列（便于对照日志里的 trace_event）
- assistant_reply：闲聊走 `SimpleAIService.reply_casual`（与主链路一致）；任务向走简短「助手应答预览」生成（非完整 analyze/generate 执行）

依赖：.env 中 DASHSCOPE_API_KEY；会多次调用大模型，耗时与费用较高。

用法：
  python scripts/regression_plan_intent_long.py
  python scripts/regression_plan_intent_long.py --turns 12 --out reports/custom.md
  python scripts/regression_plan_intent_long.py --no-task-reply   # 跳过任务向预览，仅闲聊生成回复
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    for _f in (".env", ".env.dev", ".env.prod"):
        _p = ROOT / _f
        if _p.exists():
            load_dotenv(_p)
            break
except Exception:
    pass

import plans.templates  # noqa: F401  # 注册固定 Plan

from core.ai.dashscope_client import DashScopeLLMClient
from core.intent.intent_agent import IntentAgent
from core.intent.planning_agent import PlanningAgent
from core.intent.processor import InputProcessor, IntentRecognitionUnavailableError
from core.intent.types import INTENT_CASUAL_CHAT
from core.skill_runtime import build_skill_execution_plan
from plans import (
    PLAN_TEMPLATE_DYNAMIC,
    get_plan,
    get_template_meta,
    resolve_template_id,
)
from services.ai_service import SimpleAIService


def _build_trace_id(session_id: str) -> str:
    """与 workflows.meta_workflow._build_trace_id 一致，避免 import 整张图。"""
    sid = (session_id or "no-session").strip()[:24]
    return f"{sid}-{uuid.uuid4().hex[:10]}"


def _configure_stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _env_has_dashscope_key() -> bool:
    import os

    if (os.environ.get("DASHSCOPE_API_KEY") or "").strip():
        return True
    for name in (".env", ".env.dev", ".env.prod"):
        p = ROOT / name
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = ln.strip()
            if s.startswith("DASHSCOPE_API_KEY=") and s.split("=", 1)[1].strip():
                return True
    return False


# 参照 test_10_turn_casual_intent 的短句序列，并扩展至约 32 轮
_BASE_CASUAL = [
    "北京天气如何",
    "需要",
    "继续",
    "然后呢",
    "好的",
    "再说说",
    "行",
    "还有吗",
    "嗯",
    "谢谢",
]
_EXTRA_CASUAL = [
    "你好",
    "在吗",
    "今天吃了吗",
    "随便聊聊",
    "晚安",
    "哈哈",
    "好吧",
    "知道了",
    "嗯嗯",
    "不客气",
    "周末愉快",
    "最近忙吗",
]


def _pad_turns(base: list[str], extra: list[str], n: int) -> list[str]:
    out = []
    while len(out) < n:
        out.extend(base)
        if len(out) < n:
            out.extend(extra)
    return out[:n]


def _merge_ip_context(ip_ctx: dict[str, Any], processed: dict[str, Any]) -> dict[str, Any]:
    out = dict(ip_ctx)
    sd = processed.get("structured_data") or {}
    if isinstance(sd, dict):
        for k in ("brand_name", "product_desc", "topic", "platform", "target_audience", "goal"):
            v = (sd.get(k) or "").strip()
            if v:
                out[k] = v
    return out


def _scenario_bootstrap_ip(scenario: str, turn_index: int, ip_ctx: dict[str, Any]) -> dict[str, Any]:
    """
    模拟「已进入 IP 流程」的上下文，使连续短句下仍可能命中固定模板（与真实 state 中已写入的 ip_context 一致）。
    注意：仅用 setdefault 会被 LLM 抽到的短 topic（如「小红书」）挡住，故在需命中 registry 时强制补齐关键词。
    """
    ctx = dict(ip_ctx)
    if scenario == "fixed_account_building":
        if turn_index >= 1:
            ctx["brand_name"] = (ctx.get("brand_name") or "林记手作").strip() or "林记手作"
            ctx["product_desc"] = (ctx.get("product_desc") or "手工酱料礼盒").strip() or "手工酱料礼盒"
            t = (ctx.get("topic") or "").strip()
            # account_building：选择器要求 topic 含「账号」；避免与 ip_diagnosis(账号+流量/数据) 抢优先级时用「打造」类描述
            if "账号" not in t:
                ctx["topic"] = "小红书账号打造"
            else:
                ctx["topic"] = t
    elif scenario == "fixed_content_matrix":
        if turn_index >= 1:
            t = (ctx.get("topic") or "").strip()
            if "矩阵" not in t and "选题" not in t:
                ctx["topic"] = "内容矩阵与选题规划"
            else:
                ctx["topic"] = t
            ctx.setdefault("brand_name", ctx.get("brand_name") or "测试品牌")
    elif scenario == "fixed_ip_diagnosis":
        if turn_index >= 1:
            t = (ctx.get("topic") or "").strip()
            if "账号" not in t or ("流量" not in t and "数据" not in t):
                ctx["topic"] = "抖音账号流量下滑"
            else:
                ctx["topic"] = t
    elif scenario == "casual_fixed_switch":
        # 分段：先纯闲聊 → 中段锁定账号打造模板 → 末段解除锁回动态，验证 locked_template_id 与 resolve 一致
        if turn_index <= 8:
            ctx.pop("locked_template_id", None)
            ctx.pop("plan_template_lock", None)
        elif turn_index <= 22:
            ctx["locked_template_id"] = "account_building"
            ctx["brand_name"] = (ctx.get("brand_name") or "小林").strip() or "小林"
            t = (ctx.get("topic") or "").strip()
            ctx["topic"] = t if "账号" in t else "小红书账号打造"
        else:
            ctx.pop("locked_template_id", None)
            ctx.pop("plan_template_lock", None)
    return ctx


def build_scenario_turns(turns: int) -> dict[str, list[str]]:
    n = max(1, turns)
    casual = _pad_turns(_BASE_CASUAL, _EXTRA_CASUAL, n)

    fixed_ab = [
        "我想打造个人IP，主做小红书",
        "品牌名是林记手作",
        "产品是手工酱料礼盒，想提升曝光",
    ]
    fixed_ab.extend(_pad_turns(_BASE_CASUAL, ["下一步", "然后呢", "好的", "继续"], n - len(fixed_ab)))

    fixed_cm = [
        "想做一份内容矩阵，把选题和方向理一理",
        "品牌叫测试品牌",
        "目标人群是都市白领",
    ]
    fixed_cm.extend(_pad_turns(_BASE_CASUAL, ["还有吗", "继续说", "需要", "行"], n - len(fixed_cm)))

    fixed_diag = [
        "帮我看看账号诊断，最近流量很差",
        "主要做抖音",
        "粉丝互动也下降了",
    ]
    fixed_diag.extend(_pad_turns(_BASE_CASUAL, ["然后呢", "再说说", "嗯", "谢谢"], n - len(fixed_diag)))

    # 动态：避免命中固定选择器（topic 不含账号/矩阵关键词，意图偏咨询）
    dynamic = [
        "最近短视频行业有什么新趋势",
        "竞品都在做什么类型的内容",
        "不做账号运营，只想了解下热点",
        "帮我就当前话题给点思路，先不要生成完整文案",
    ]
    dynamic.extend(
        _pad_turns(
            ["还有呢", "展开说说", "为什么", "举个例子", "好的", "继续", "嗯", "谢谢"],
            _EXTRA_CASUAL,
            n - len(dynamic),
        )
    )

    # 闲聊 ↔ 固定 切换
    switch_cf: list[str] = []
    switch_cf.extend(_pad_turns(_BASE_CASUAL[:5], _EXTRA_CASUAL[:3], 8))
    switch_cf.extend(
        [
            "我想做小红书账号打造，品牌是小林",
            "产品是知识专栏",
        ]
    )
    switch_cf.extend(_pad_turns(["继续", "需要", "然后呢", "好的"], _BASE_CASUAL, 10))
    switch_cf.extend(["今天天气怎么样", "谢谢哈", "我们闲聊一下", "在吗"])
    switch_cf.extend(_pad_turns(_EXTRA_CASUAL, _BASE_CASUAL, n - len(switch_cf)))

    # 打断 / 退出 / 再进入
    interrupt = [
        "我要做内容矩阵，品牌测试牌",
        "话题是选题规划",
        "继续",
        "需要",
        "算了不做了，先不规划了",
        "我们闲聊吧，今天挺累的",
        "好的知道了",
        "还是回到刚才的内容矩阵吧",
        "品牌还是测试牌",
        "继续执行",
        "又不想做了，退出任务",
        "谢谢",
    ]
    interrupt.extend(_pad_turns(_BASE_CASUAL, _EXTRA_CASUAL, n - len(interrupt)))

    return {
        "pure_casual": casual,
        "fixed_account_building": fixed_ab[:n],
        "fixed_content_matrix": fixed_cm[:n],
        "fixed_ip_diagnosis": fixed_diag[:n],
        "dynamic_plan": dynamic[:n],
        "casual_fixed_switch": switch_cf[:n],
        "interrupt_and_resume": interrupt[:n],
    }


def _plugins_join(plugins: Any) -> str:
    if plugins is None:
        return ""
    if isinstance(plugins, list):
        return ",".join(str(p) for p in plugins)
    return str(plugins)


def _summarize_plan(template_id: str, plan_result: dict[str, Any] | None, fixed_steps: list[dict] | None) -> str:
    if fixed_steps:
        parts = []
        for s in fixed_steps:
            if not isinstance(s, dict):
                continue
            parts.append(f"{s.get('step', '?')}[{_plugins_join(s.get('plugins'))}]")
        return f"fixed:{template_id} → " + " | ".join(parts[:12]) + (" …" if len(parts) > 12 else "")
    if plan_result:
        steps = plan_result.get("steps") or []
        seq = []
        for s in steps[:15]:
            if isinstance(s, dict):
                seq.append(f"{s.get('step', '?')}[{_plugins_join(s.get('plugins'))}]")
        return f"dynamic task={plan_result.get('task_type', '')} → " + " | ".join(seq)
    return "—"


def _normalize_plugins_list(pls: Any) -> list[str]:
    if isinstance(pls, str):
        return [pls] if pls.strip() else []
    if isinstance(pls, list):
        return [str(p).strip() for p in pls if str(p).strip()]
    return []


def _skill_runtime_first_analyze_json(steps: list[dict] | None, user_id: str) -> tuple[str, str]:
    """
    从步骤列表中取第一个 analyze 的 plugins，返回 (JSON 摘要, ab_bucket)。
    """
    if not steps:
        return "—", ""
    for s in steps:
        if not isinstance(s, dict):
            continue
        if (s.get("step") or "").lower() != "analyze":
            continue
        pls = _normalize_plugins_list(s.get("plugins"))
        if not pls:
            continue
        plan = build_skill_execution_plan(pls, user_id=user_id)
        js = json.dumps(
            {
                "resolved_plugins": plan.get("resolved_plugins"),
                "skill_ids": plan.get("skill_ids"),
                "ab_bucket": plan.get("ab_bucket"),
            },
            ensure_ascii=False,
        )
        return js, str(plan.get("ab_bucket") or "")
    return "—", ""


def _plan_steps_all_casual_reply(steps: list[Any] | None) -> bool:
    if not steps:
        return False
    for s in steps:
        if not isinstance(s, dict):
            return False
        if (s.get("step") or "").lower() != "casual_reply":
            return False
    return True


def _history_text_for_reply_casual(history: list[str]) -> str:
    if not history:
        return ""
    parts = [ln for ln in history[-24:] if ln.strip()]
    return "以下是近期对话：\n" + "\n".join(parts) + "\n\n" if parts else ""


async def _generate_task_assistant_preview(
    ai: SimpleAIService,
    *,
    user_message: str,
    conversation_context: str,
    plan_summary: str,
    template_id: str,
    ip_context: dict[str, str],
) -> str:
    """
    非完整工作流：仅生成「此刻助手应对用户说的」2～5 句预览，便于人工判断衔接是否合理。
    """
    client = await ai.router.route("planning", "low")
    body = f"""你是 AI 营销助手。根据以下状态，用 2～5 句中文直接对用户说话（第一人称），语气专业友好。
不要编造具体粉丝数、阅读量等数据；若尚需分析/检索，可明确说「接下来我会为你……」。

【传入意图识别/规划的上下文节选】
{conversation_context[:2800]}

【用户当前一句】
{user_message}

【ip_context】
{json.dumps(ip_context, ensure_ascii=False)[:900]}

【计划】
模板/计划 ID：{template_id}
摘要：{plan_summary}

只输出助手要说给用户的内容，不要小标题或列表符号。"""
    r = await client.ainvoke([HumanMessage(content=body)])
    return (getattr(r, "content", None) or str(r)).strip()


async def run_scenario(
    name: str,
    messages: list[str],
    *,
    proc: InputProcessor,
    intent_agent: IntentAgent,
    planning_agent: PlanningAgent,
    ai: SimpleAIService,
    session_id: str,
    user_id: str,
    no_task_reply: bool = False,
) -> list[dict[str, Any]]:
    history: list[str] = []
    ip_context: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []

    for i, msg in enumerate(messages, 1):
        conv = "\n".join(history[-24:])
        trace_id = _build_trace_id(session_id)
        trace_events: list[dict[str, Any]] = [
            {
                "trace_id": trace_id,
                "stage": "regression",
                "action": "turn_start",
                "turn": i,
                "scenario": name,
                "session_id": session_id,
                "user_id": user_id,
            },
            {
                "trace_id": trace_id,
                "stage": "context",
                "action": "conversation_context_for_intent",
                "chars": len(conv),
                "preview_tail": conv[-220:] if conv else "",
            },
        ]
        row: dict[str, Any] = {
            "turn": i,
            "input": msg,
            "trace_id": trace_id,
            "conversation_context_for_intent": conv,
            "trace_events": trace_events,
            "errors": [],
        }

        processed: dict[str, Any] | None = None
        try:
            processed = await proc.process(
                raw_input=msg,
                session_id=session_id,
                user_id=user_id,
                conversation_context=conv,
            )
        except IntentRecognitionUnavailableError as e:
            row["errors"].append(f"InputProcessor: {e}")
            trace_events.append(
                {
                    "trace_id": trace_id,
                    "stage": "intent",
                    "action": "input_processor_error",
                    "error": str(e)[:200],
                }
            )
            row["assistant_reply_path"] = "error"
            row["assistant_reply"] = "（意图识别不可用，未生成助手回复。）"
            rows.append(row)
            history.append(f"用户：{msg}")
            history.append(f"助手：{row['assistant_reply']}")
            continue
        except Exception as e:
            row["errors"].append(f"InputProcessor: {type(e).__name__}: {e}")
            trace_events.append(
                {
                    "trace_id": trace_id,
                    "stage": "intent",
                    "action": "input_processor_exception",
                    "error": str(e)[:200],
                }
            )
            row["assistant_reply_path"] = "error"
            row["assistant_reply"] = f"（InputProcessor 异常：{type(e).__name__}，未生成助手回复。）"
            rows.append(row)
            history.append(f"用户：{msg}")
            history.append(f"助手：{row['assistant_reply']}")
            continue

        assert processed is not None
        row["input_processor"] = {
            "intent": processed.get("intent"),
            "explicit_content_request": processed.get("explicit_content_request"),
            "structured_data": processed.get("structured_data") or {},
            "raw_query": processed.get("raw_query"),
        }
        trace_events.append(
            {
                "trace_id": trace_id,
                "stage": "intent",
                "action": "input_processor_ok",
                "intent": processed.get("intent"),
                "explicit_content_request": processed.get("explicit_content_request"),
            }
        )

        ip_context = _merge_ip_context(ip_context, processed)
        ip_context = _scenario_bootstrap_ip(name, i, ip_context)
        trace_events.append(
            {
                "trace_id": trace_id,
                "stage": "context",
                "action": "ip_context_after_merge",
                "ip_context": dict(ip_context),
            }
        )

        try:
            coarse = await intent_agent.classify_intent(user_input=msg, conversation_context=conv)
        except Exception as e:
            row["errors"].append(f"IntentAgent: {type(e).__name__}: {e}")
            coarse = {
                "intent": "free_discussion",
                "confidence": 0.0,
                "raw_query": msg,
                "notes": f"error:{e}",
                "need_clarification": True,
            }
            trace_events.append(
                {
                    "trace_id": trace_id,
                    "stage": "intent",
                    "action": "intent_agent_exception",
                    "error": str(e)[:200],
                }
            )
        else:
            trace_events.append(
                {
                    "trace_id": trace_id,
                    "stage": "intent",
                    "action": "intent_agent_ok",
                    "intent": coarse.get("intent"),
                    "confidence": coarse.get("confidence"),
                    "need_clarification": coarse.get("need_clarification"),
                }
            )

        row["intent_agent"] = {
            "intent": coarse.get("intent"),
            "confidence": coarse.get("confidence"),
            "need_clarification": coarse.get("need_clarification"),
            "notes": (coarse.get("notes") or "")[:200],
        }

        template_id = resolve_template_id(coarse.get("intent") or "", ip_context)
        row["plan_template_id"] = template_id
        meta = get_template_meta(template_id) if template_id else None
        row["template_meta_name"] = (meta or {}).get("name") or ""

        fixed_steps = None
        plan_dyn: dict[str, Any] | None = None
        if template_id and template_id != PLAN_TEMPLATE_DYNAMIC:
            fixed_steps = get_plan(template_id)
        else:
            try:
                plan_dyn = await planning_agent.plan_steps(
                    intent_data=coarse,
                    user_data=ip_context,
                    conversation_context=conv,
                )
            except Exception as e:
                row["errors"].append(f"PlanningAgent: {type(e).__name__}: {e}")
                trace_events.append(
                    {
                        "trace_id": trace_id,
                        "stage": "plan",
                        "action": "planning_agent_error",
                        "error": str(e)[:200],
                    }
                )

        row["plan_summary"] = _summarize_plan(template_id, plan_dyn, fixed_steps)
        dyn_steps = (
            plan_dyn.get("steps")
            if plan_dyn and isinstance(plan_dyn.get("steps"), list)
            else None
        )
        effective_steps: list[dict] | None = None
        if fixed_steps:
            effective_steps = fixed_steps
        elif plan_dyn and isinstance(plan_dyn.get("steps"), list):
            effective_steps = [s for s in plan_dyn["steps"] if isinstance(s, dict)]

        sk_json, sk_ab = _skill_runtime_first_analyze_json(
            effective_steps, user_id=f"{user_id}:{name}"
        )
        row["skill_runtime_first_analyze"] = sk_json
        row["skill_ab_bucket"] = sk_ab
        trace_events.append(
            {
                "trace_id": trace_id,
                "stage": "plan",
                "action": "resolved",
                "plan_template_id": template_id,
                "plan_summary": row["plan_summary"][:500],
                "is_fixed": bool(template_id and template_id != PLAN_TEMPLATE_DYNAMIC),
            }
        )
        if sk_json != "—":
            trace_events.append(
                {
                    "trace_id": trace_id,
                    "stage": "step",
                    "step": "analyze",
                    "action": "skill_runtime_plan",
                    "skill_ab_bucket": sk_ab,
                    "runtime": json.loads(sk_json) if sk_json != "—" else {},
                }
            )

        # ---------- 助手回复（闲聊与主站一致；任务向为预览） ----------
        ht = _history_text_for_reply_casual(history)
        fine_i = processed.get("intent")
        coarse_i = (coarse.get("intent") or "").strip().lower()
        dyn_steps = plan_dyn.get("steps") if plan_dyn else None

        assistant_reply = ""
        reply_path = "skipped"

        if fine_i == INTENT_CASUAL_CHAT:
            reply_path = "casual_reply"
            assistant_reply = await ai.reply_casual(message=msg, history_text=ht, user_context="")
        elif coarse_i == "casual_chat":
            reply_path = "casual_reply_coarse"
            assistant_reply = await ai.reply_casual(message=msg, history_text=ht, user_context="")
        elif coarse.get("need_clarification"):
            reply_path = "clarification"
            assistant_reply = await ai.reply_casual(
                message=msg,
                history_text=ht,
                clarification_mode=True,
                clarification_kind="intent_unclear",
                clarification_question=str(coarse.get("clarification_question") or ""),
                user_context="",
            )
        elif plan_dyn and _plan_steps_all_casual_reply(dyn_steps):
            reply_path = "casual_reply_plan"
            assistant_reply = await ai.reply_casual(message=msg, history_text=ht, user_context="")
        elif no_task_reply:
            reply_path = "skipped_no_task_reply"
            assistant_reply = (
                "（已开启 --no-task-reply：本脚本未生成任务向助手话术预览；"
                "线上完整应答需走 meta_workflow 执行 analyze/generate。）"
            )
        else:
            reply_path = "task_preview"
            try:
                assistant_reply = await _generate_task_assistant_preview(
                    ai,
                    user_message=msg,
                    conversation_context=conv,
                    plan_summary=row["plan_summary"],
                    template_id=template_id or "",
                    ip_context=ip_context,
                )
            except Exception as e:
                row["errors"].append(f"task_preview: {type(e).__name__}: {e}")
                assistant_reply = f"（任务向预览生成失败：{type(e).__name__}）"

        row["assistant_reply_path"] = reply_path
        row["assistant_reply"] = assistant_reply
        trace_events.append(
            {
                "trace_id": trace_id,
                "stage": "assistant",
                "action": "reply_generated",
                "path": reply_path,
                "reply_chars": len(assistant_reply or ""),
            }
        )

        history.append(f"用户：{msg}")
        history.append(f"助手：{(assistant_reply or '')[:800]}")
        rows.append(row)

    return rows


def _md_escape_cell(s: str, max_len: int) -> str:
    t = (s or "").replace("|", "\\|").replace("\n", " ")
    return t[:max_len] + ("…" if len(t) > max_len else "")


def rows_to_markdown(
    title: str,
    scenario_results: dict[str, list[dict[str, Any]]],
    turns: int,
) -> str:
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 生成时间（UTC）：{datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- 每场景轮次：{turns}")
    lines.append(
        "- **意图**：`InputProcessor` 为细粒度（与 `analyze-deep` 一致）；`IntentAgent` 为粗粒度（与 `meta_workflow` / `ip_build.plan_once` 一致）。"
    )
    lines.append(
        "- **trace_id**：格式与 `meta_workflow._build_trace_id` 一致；`trace_events` 为本脚本合成的伪链路节点，字段风格对齐线上 `trace_event` 日志。"
    )
    lines.append(
        "- **助手回复**：`casual_reply` / `clarification` 等路径调用 `SimpleAIService.reply_casual`（与主站闲聊/澄清一致）；`task_preview` 为任务向**话术预览**（未真实执行 analyze/generate 插件）。"
    )
    lines.append(
        "- 固定 Plan 场景对 `ip_context` 有稳定化（`_scenario_bootstrap_ip`），便于短句续聊仍命中同一固定模板。"
    )
    lines.append("")

    for scen, rows in scenario_results.items():
        lines.append(f"## 场景：`{scen}`")
        lines.append("")
        lines.append(
            "| 轮次 | trace_id | 用户输入 | 细意图 | 粗意图 | 模板 | 回复路径 | 助手回复预览 | AB | 错误 |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in rows:
            ip = r.get("input_processor") or {}
            ia = r.get("intent_agent") or {}
            err = "; ".join(r.get("errors") or []) or "—"
            lines.append(
                "| {turn} | `{tid}` | {inp} | {fine} | {coarse} | {tpl} | {rp} | {ar} | {ab} | {er} |".format(
                    turn=r.get("turn"),
                    tid=_md_escape_cell(str(r.get("trace_id") or ""), 36),
                    inp=_md_escape_cell(str(r.get("input") or ""), 28),
                    fine=_md_escape_cell(str(ip.get("intent") or "—"), 14),
                    coarse=_md_escape_cell(str(ia.get("intent") or "—"), 14),
                    tpl=_md_escape_cell(str(r.get("plan_template_id") or "—"), 18),
                    rp=_md_escape_cell(str(r.get("assistant_reply_path") or "—"), 18),
                    ar=_md_escape_cell(str(r.get("assistant_reply") or ""), 44),
                    ab=_md_escape_cell(str(r.get("skill_ab_bucket") or "—"), 3),
                    er=_md_escape_cell(err, 24),
                )
            )
        lines.append("")
        lines.append("### 按轮详情（上下文 · trace_events · 完整助手回复）")
        lines.append("")
        for r in rows:
            tid = r.get("trace_id") or ""
            lines.append(f"<details>")
            lines.append(f"<summary><strong>轮次 {r.get('turn')}</strong> · <code>{tid}</code></summary>")
            lines.append("")
            lines.append("#### 传入意图识别的上下文 `conversation_context`")
            lines.append("")
            lines.append("```text")
            lines.append((r.get("conversation_context_for_intent") or "").strip() or "（空）")
            lines.append("```")
            lines.append("")
            lines.append("#### trace_events（伪全链路，对齐线上 JSON 日志结构）")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(r.get("trace_events") or [], ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
            lines.append("#### 助手回复 `assistant_reply`")
            lines.append("")
            lines.append(f"- **路径** `{r.get('assistant_reply_path')}`")
            lines.append("")
            lines.append("```text")
            lines.append((r.get("assistant_reply") or "").strip() or "（空）")
            lines.append("```")
            lines.append("")
            ip = r.get("input_processor") or {}
            ia = r.get("intent_agent") or {}
            lines.append("#### 意图与计划摘要")
            lines.append("")
            lines.append(f"- 细意图 `{ip.get('intent')}` · explicit `{ip.get('explicit_content_request')}`")
            lines.append(
                f"- 粗意图 `{ia.get('intent')}` · conf `{ia.get('confidence')}` · need_clarification `{ia.get('need_clarification')}`"
            )
            lines.append(f"- 模板 `{r.get('plan_template_id')}` · {r.get('template_meta_name') or ''}")
            lines.append(f"- 计划摘要：{r.get('plan_summary') or '—'}")
            lines.append(f"- skill_runtime（首 analyze）：`{r.get('skill_runtime_first_analyze') or '—'}`")
            lines.append("")
            lines.append("</details>")
            lines.append("")

        lines.append("<details><summary>结构化字段 JSON（按轮，精简）</summary>")
        lines.append("")
        lines.append("```json")
        lines.append(
            json.dumps(
                [
                    {
                        "turn": r.get("turn"),
                        "trace_id": r.get("trace_id"),
                        "input": r.get("input"),
                        "structured_data": (r.get("input_processor") or {}).get("structured_data"),
                        "notes": (r.get("intent_agent") or {}).get("notes"),
                        "assistant_reply_path": r.get("assistant_reply_path"),
                    }
                    for r in rows
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


async def async_main() -> int:
    _configure_stdout_utf8()
    parser = argparse.ArgumentParser(description="Plan / 意图长对话回归，输出 Markdown")
    parser.add_argument("--turns", type=int, default=32, help="每场景轮次（默认 32）")
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="输出 Markdown 路径（默认 reports/regression_plan_intent_<timestamp>.md）",
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default="",
        help="逗号分隔子集，如 pure_casual,dynamic_plan；空表示全部",
    )
    parser.add_argument(
        "--no-task-reply",
        action="store_true",
        help="跳过任务向助手话术预览（仍对闲聊/澄清路径调用 reply_casual）",
    )
    args = parser.parse_args()

    if not _env_has_dashscope_key():
        print("错误：未检测到 DASHSCOPE_API_KEY，请在 .env 中配置后重试。", file=sys.stderr)
        return 2

    turns = min(80, max(1, args.turns))
    all_scenarios = build_scenario_turns(turns)
    if args.scenarios.strip():
        wanted = {x.strip() for x in args.scenarios.split(",") if x.strip()}
        all_scenarios = {k: v for k, v in all_scenarios.items() if k in wanted}
        if not all_scenarios:
            print("错误：--scenarios 未匹配任何场景", file=sys.stderr)
            return 2

    llm = DashScopeLLMClient()
    ai = SimpleAIService(llm_client=llm)
    proc = InputProcessor(ai_service=ai, use_rule_based_intent_filter=True)
    intent_agent = IntentAgent(llm)
    planning_agent = PlanningAgent(llm)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out.strip() else reports_dir / f"regression_plan_intent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    results: dict[str, list[dict[str, Any]]] = {}
    for scen_name, msgs in all_scenarios.items():
        sid = f"reglong_{scen_name}"
        uid = f"reglong_user_{scen_name}"
        results[scen_name] = await run_scenario(
            scen_name,
            msgs,
            proc=proc,
            intent_agent=intent_agent,
            planning_agent=planning_agent,
            ai=ai,
            session_id=sid,
            user_id=uid,
            no_task_reply=args.no_task_reply,
        )

    actual_turns = max((len(v) for v in results.values()), default=turns)
    md = rows_to_markdown("Plan / 意图 长对话回归报告", results, actual_turns)
    out_path.write_text(md, encoding="utf-8")
    print(str(out_path.resolve()))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())

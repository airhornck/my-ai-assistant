#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
固定 Plan 全量旅程回归（模拟真实对话模式，不依赖外网 LLM）：

- 参考对话：你好 → 天气 → 暂时没有 → 业务诉求 → 品牌补齐 → 多轮「继续」直到 phase=done
- IP 三模板（account_building / content_matrix / ip_diagnosis）：完整 intake + 逐步执行
- 四能力固定模板：从 phase=executing 注入 get_plan()，逐步「继续」直到 done
- 分批：每完成 2 个模板后打印「── 新对话 ──」，再测下一批（共 4 批覆盖 7 个固定模板）
- 长对话：约 30 轮（含闲聊 + 账号打造全流程）

运行：
  python scripts/run_fixed_plans_full_journey.py

退出码：0 全部通过，1 存在失败项
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Callable, Awaitable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.messages import AIMessage  # noqa: E402

from core.intent.intent_agent import IntentAgent  # noqa: E402
from models.request import ContentRequest  # noqa: E402
from plans import (  # noqa: E402
    CAPABILITY_TEMPLATE_CASE_LIBRARY,
    CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING,
    CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX,
    CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT,
    TEMPLATE_ACCOUNT_BUILDING,
    TEMPLATE_CONTENT_MATRIX,
    TEMPLATE_IP_DIAGNOSIS,
    get_plan,
    get_template_meta,
)
from workflows.types import IP_BUILD_PHASE_DONE  # noqa: E402


def _utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _payload(
    raw: str,
    *,
    brand_name: str = "",
    product_desc: str = "",
    topic: str = "",
    platform: str = "",
) -> str:
    return json.dumps(
        {
            "raw_query": raw,
            "brand_name": brand_name,
            "product_desc": product_desc,
            "topic": topic,
            "platform": platform,
            "conversation_context": "",
            "tags": [],
        },
        ensure_ascii=False,
    )


def _merge(prev: dict, out: dict) -> dict:
    m = dict(prev)
    for k, v in out.items():
        m[k] = v
    return m


def _intent_factory(intent: str) -> Callable[..., Awaitable[dict]]:
    async def _fake(self: Any, user_input: str = "", conversation_context: str = "") -> dict:
        return {
            "intent": intent,
            "confidence": 0.92,
            "raw_query": (user_input or "").strip(),
            "notes": "fixed_plan_journey_mock",
        }

    return _fake


class StubLLM:
    """满足 Intent 备用 invoke、IP casual_reply 的 ainvoke。"""

    async def invoke(self, messages: list, *args: Any, **kwargs: Any) -> Any:
        class R:
            content = json.dumps(
                {"intent": "free_discussion", "confidence": 0.9, "raw_query": "", "notes": "stub"},
                ensure_ascii=False,
            )

        return R()

    async def ainvoke(self, messages: list, config: Any = None, **kwargs: Any) -> AIMessage:
        return AIMessage(content="stub闲聊回复")


class MiniAIService:
    """仅实现 IP 单步执行所需 analyze / generate / evaluate。"""

    def __init__(self) -> None:
        self._llm = StubLLM()

    async def analyze(
        self,
        request: ContentRequest,
        preference_context: Any = None,
        context_fingerprint: Any = None,
        analysis_plugins: Any = None,
    ) -> tuple[dict, bool]:
        return (
            {
                "angle": "【stub】分析摘要",
                "account_diagnosis": "【stub】诊断要点",
            },
            False,
        )

    async def generate(self, *args: Any, **kwargs: Any) -> str:
        return "【stub】生成正文用于评估步骤"

    async def evaluate_content(self, content: str, context: dict) -> dict[str, Any]:
        return {"overall_score": 8, "suggestions": "【stub】评估建议"}


class _DummyGraph:
    async def ainvoke(self, *args: Any, **kwargs: Any) -> dict:
        return {}


class _StubWeb:
    async def search(self, *args: Any, **kwargs: Any) -> list:
        return []

    def format_results_as_context(self, results: list) -> str:
        return ""


class _StubMem:
    async def get_memory_for_analyze(self, *args: Any, **kwargs: Any) -> dict:
        return {"preference_context": "", "effective_tags": []}

    async def get_user_summary(self, *args: Any, **kwargs: Any) -> str:
        return ""


class _StubKb:
    async def retrieve(self, *args: Any, **kwargs: Any) -> list:
        return []


async def _run_journey(
    workflow: Any,
    *,
    thread_id: str,
    initial: dict,
    dialogue_lines: list[str],
    continue_tokens: list[str] | None = None,
    max_rounds: int = 45,
    expected_template_id: str | None = None,
) -> tuple[dict, list[str]]:
    """先按 dialogue_lines 发送，再循环 continue 直到 done。"""
    issues: list[str] = []
    config = {"configurable": {"thread_id": thread_id}}
    state = dict(initial)
    ct = continue_tokens or ["继续", "好的", "下一步", "继续执行"]
    ci = 0

    async def _turn(user_line: str, extra: dict | None = None) -> dict:
        nonlocal state
        ex = extra or {}
        raw = user_line
        state["user_input"] = _payload(
            raw,
            brand_name=ex.get("brand_name", state.get("ip_context", {}).get("brand_name", "")),
            product_desc=ex.get("product_desc", state.get("ip_context", {}).get("product_desc", "")),
            topic=ex.get("topic", state.get("ip_context", {}).get("topic", "")),
            platform=ex.get("platform", state.get("ip_context", {}).get("platform", "")),
        )
        out = await workflow.ainvoke(state, config=config)
        state = _merge(state, out)
        return out

    for line in dialogue_lines:
        await _turn(line)

    rounds = 0
    while (state.get("phase") or "") != IP_BUILD_PHASE_DONE and rounds < max_rounds:
        tok = ct[ci % len(ct)]
        ci += 1
        extra: dict = {}
        pq = state.get("pending_questions") or []
        if any(isinstance(q, dict) and q.get("key") == "platform" for q in pq):
            extra["platform"] = "B站"
            tok = "主要在B站发布"
        await _turn(tok, extra=extra)
        rounds += 1

    if (state.get("phase") or "") != IP_BUILD_PHASE_DONE:
        issues.append(f"未在 {max_rounds} 轮内结束: phase={state.get('phase')!r}")

    plan = state.get("plan") or []
    outs = state.get("step_outputs") or []
    if plan and len(outs) < len(plan):
        issues.append(f"步骤未完成: step_outputs={len(outs)} plan_len={len(plan)}")

    tid = (state.get("plan_template_id") or "").strip()
    if expected_template_id and tid != expected_template_id:
        issues.append(f"模板 ID 不符: 期望 {expected_template_id!r} 实际 {tid!r}")

    ptn = (state.get("plan_template_name") or "").strip()
    if expected_template_id and expected_template_id != "dynamic" and not ptn:
        issues.append(f"plan_template_name 为空（模板 {expected_template_id}）")

    return state, issues


async def main_async() -> int:
    _utf8_stdout()
    import workflows.meta_workflow as meta_mod

    meta_mod.build_analysis_brain_subgraph = lambda ai_svc: _DummyGraph()
    meta_mod.build_generation_brain_subgraph = lambda ai_svc: _DummyGraph()

    ai = MiniAIService()
    wf = meta_mod.build_meta_workflow(
        ai_service=ai,
        web_searcher=_StubWeb(),
        memory_service=_StubMem(),
        knowledge_port=_StubKb(),
    )

    base: dict[str, Any] = {
        "user_input": "",
        "analysis": "",
        "content": "",
        "session_id": "e2e_session",
        "user_id": "e2e_user",
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
        "plan_template_name": "",
        "ip_build_handled": False,
    }

    all_issues: list[tuple[str, list[str]]] = []
    report_lines: list[str] = ["# 固定 Plan 全量旅程回归报告\n"]

    def banner(title: str) -> None:
        report_lines.append(f"\n## {title}\n")
        print(f"\n{'='*60}\n{title}\n{'='*60}")

    # ---------- 批次 1：账号打造 + 内容矩阵 ----------
    banner("批次 1（对话 1）：账号打造 account_building")

    lines_ab = [
        "你好",
        "今天天气不错",
        "暂时没有",
        "我打算将我的教育机构在B站上建一个账号",
        "品牌叫小红果",
    ]
    with patch.object(IntentAgent, "classify_intent", new=_intent_factory("free_discussion")):
        st, iss = await _run_journey(
            wf,
            thread_id="journey_b1_ab",
            initial=dict(base),
            dialogue_lines=lines_ab,
            expected_template_id=TEMPLATE_ACCOUNT_BUILDING,
        )
    all_issues.append(("account_building", iss))
    report_lines.append(f"- **account_building**: step_outputs={len(st.get('step_outputs') or [])} issues={iss or '无'}\n")

    banner("批次 1（对话 2）：内容矩阵 content_matrix")
    lines_cm = [
        "你好",
        "今天天气不错",
        "暂时没有",
        "我想做教育机构的小红书内容矩阵和选题规划，提升曝光",
        "品牌名叫青禾矩阵",
    ]
    with patch.object(IntentAgent, "classify_intent", new=_intent_factory("内容运营规划")):
        st2, iss2 = await _run_journey(
            wf,
            thread_id="journey_b1_cm",
            initial=dict(base),
            dialogue_lines=lines_cm,
            expected_template_id=TEMPLATE_CONTENT_MATRIX,
        )
    all_issues.append(("content_matrix", iss2))
    report_lines.append(f"- **content_matrix**: step_outputs={len(st2.get('step_outputs') or [])} issues={iss2 or '无'}\n")

    report_lines.append("\n### ── 新对话（批次 2）──\n")

    # ---------- 批次 2：IP 诊断 + 能力模板 ranking ----------
    banner("批次 2（对话 3）：IP 诊断 ip_diagnosis")
    lines_ipd = [
        "你好",
        "今天天气不错",
        "暂时没有",
        "我B站账号最近流量很差，帮我诊断一下账号问题",
        "品牌叫小蓝果教育",
    ]
    with patch.object(IntentAgent, "classify_intent", new=_intent_factory("account_diagnosis")):
        st3, iss3 = await _run_journey(
            wf,
            thread_id="journey_b2_ipd",
            initial=dict(base),
            dialogue_lines=lines_ipd,
            expected_template_id=TEMPLATE_IP_DIAGNOSIS,
        )
    all_issues.append(("ip_diagnosis", iss3))
    report_lines.append(f"- **ip_diagnosis**: step_outputs={len(st3.get('step_outputs') or [])} issues={iss3 or '无'}\n")

    async def run_execute_only(
        template_id: str,
        thread_suffix: str,
        label: str,
    ) -> None:
        plan = get_plan(template_id)
        if not plan:
            all_issues.append((label, [f"get_plan({template_id!r}) 为空"]))
            report_lines.append(f"- **{label}**: ❌ 无步骤\n")
            return
        meta = get_template_meta(template_id) or {}
        name = (meta.get("name") or template_id).strip()
        st0 = dict(base)
        st0.update(
            {
                "phase": "executing",
                "plan": plan,
                "plan_template_id": template_id,
                "plan_template_name": name,
                "current_step": 0,
                "step_outputs": [],
                "pending_questions": [],
                "ip_context": {
                    "brand_name": "E2E品牌",
                    "product_desc": "在线教育",
                    "topic": "B站账号增长",
                    "platform": "B站",
                },
            }
        )
        issues: list[str] = []
        cfg = {"configurable": {"thread_id": f"journey_exec_{thread_suffix}"}}
        state = dict(st0)
        rounds = 0
        while (state.get("phase") or "") != IP_BUILD_PHASE_DONE and rounds < 40:
            pq = state.get("pending_questions") or []
            plat = "B站"
            raw = "继续"
            if any(isinstance(q, dict) and q.get("key") == "platform" for q in pq):
                raw = "选用B站"
            state["user_input"] = _payload(
                raw,
                brand_name="E2E品牌",
                product_desc="在线教育",
                topic="B站账号增长",
                platform=plat,
            )
            out = await wf.ainvoke(state, cfg)
            state = _merge(state, out)
            rounds += 1
        if (state.get("phase") or "") != IP_BUILD_PHASE_DONE:
            issues.append("execute_only 未在轮次内 done")
        outs = state.get("step_outputs") or []
        if len(outs) < len(plan):
            issues.append(f"步骤数不足 outs={len(outs)} plan={len(plan)}")
        all_issues.append((label, issues))
        report_lines.append(f"- **{label}** (`{template_id}`): steps_done={len(outs)}/{len(plan)} issues={issues or '无'}\n")

    banner("批次 2（对话 4）：能力 — 内容方向榜单")
    await run_execute_only(CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING, "rank", "cap_content_direction_ranking")

    report_lines.append("\n### ── 新对话（批次 3）──\n")

    banner("批次 3：能力 — 案例库 + 内容定位矩阵")
    await run_execute_only(CAPABILITY_TEMPLATE_CASE_LIBRARY, "case", "cap_case_library")
    await run_execute_only(CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX, "pos", "cap_positioning_matrix")

    report_lines.append("\n### ── 新对话（批次 4）──\n")

    banner("批次 4：能力 — 每周决策快照")
    await run_execute_only(CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT, "weekly", "cap_weekly_snapshot")

    # ---------- 长对话 ~30 轮 ----------
    banner("长对话 stress（≈30 轮）：闲聊 + 账号打造直至 done")
    long_lines = (
        ["你好", "今天天气不错", "暂时没有"]
        + [f"闲聊第{i}句" for i in range(1, 19)]  # +18 => 21 前缀
        + [
            "我打算将我的机构在B站做账号",
            "品牌叫长跑品牌",
        ]
    )
    with patch.object(IntentAgent, "classify_intent", new=_intent_factory("free_discussion")):
        st_long, iss_long = await _run_journey(
            wf,
            thread_id="journey_stress_30",
            initial=dict(base),
            dialogue_lines=long_lines,
            max_rounds=35,
            expected_template_id=TEMPLATE_ACCOUNT_BUILDING,
        )
    total_turns = len(long_lines) + 35  # 上限
    all_issues.append(("stress_30_rounds", iss_long))
    report_lines.append(
        f"- **stress**: 前置轮次≈{len(long_lines)} + 推进轮次上限35；"
        f"最终 phase={st_long.get('phase')!r} step_outputs={len(st_long.get('step_outputs') or [])} issues={iss_long or '无'}\n"
    )
    print(f"  [stress] dialogue_prefix={len(long_lines)} final_phase={st_long.get('phase')!r}")

    # ---------- 汇总 ----------
    banner("汇总：已知问题与修复状态")
    report_lines.append("\n## 问题列表（本轮检测）\n")
    failed = False
    for name, issues in all_issues:
        if issues:
            failed = True
            print(f"  ❌ {name}: {issues}")
            for it in issues:
                report_lines.append(f"- [{name}] {it}\n")
        else:
            print(f"  ✅ {name}")
            report_lines.append(f"- [{name}] 无异常\n")

    report_lines.append("\n## 已修复项（代码现状，供对照）\n")
    report_lines.append(
        "- DashScopeLLMClient 增加 `ainvoke`，分析插件与 IP casual_reply 不再报 `ainv` 缺失。\n"
        "- IP 执行失败追问：支持「重试/跳过/好的」等，避免死循环重复同一错误。\n"
        "- `plan_template_name` 写入 state / API / 前端策略脑展示；计划就绪文案含模板展示名。\n"
        "- 流式与会话写回包含 `plan_template_name`。\n"
        "- `intake_guide.infer_fields`：建/开/注册账号、内容矩阵话术、品牌名叫/品牌叫、流量/诊断等补全，避免卡在 intake。\n"
        "- 自动化回归中：若 `pending_questions` 含 `platform`，后续轮次自动带 `platform=B站` 以跑完含 `generate` 的固定 Plan。\n"
    )
    report_lines.append("\n## 附录：全量测试过程中曾暴露的问题（均已对照修复）\n")
    report_lines.append("| # | 现象 | 处理 |\n|---|------|------|\n")
    report_lines.append(
        "| 1 | 插件调用 `llm.ainvoke`，DashScope 客户端无此方法 | `DashScopeLLMClient.ainvoke` 返回 `AIMessage` |\n"
    )
    report_lines.append(
        "| 2 | 执行失败后用户答「好的」反复重试同一步 | `execute_one_step_node` 识别 `_error` 追问并重试/跳过 |\n"
    )
    report_lines.append(
        "| 3 | 计划展示名未出现在 API/策略脑 | `plan_template_name` 全链路 + 文案 `_ip_build_plan_ready_message` |\n"
    )
    report_lines.append(
        "| 4 | 「建一个账号」未推断 topic，「品牌叫X」未推断 brand | 扩展 `infer_fields` 规则 |\n"
    )
    report_lines.append(
        "| 5 | generate 缺 platform 卡住 executing | 测试脚本遇 `platform` 追问自动补全；真实用户需选平台 |\n"
    )

    out_path = ROOT / "docs" / "FIXED_PLANS_FULL_REGRESSION_REPORT.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"\n报告已写入: {out_path.relative_to(ROOT)}")

    return 1 if failed else 0


def main() -> None:
    code = asyncio.run(main_async())
    raise SystemExit(code)


if __name__ == "__main__":
    main()

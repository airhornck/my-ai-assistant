"""
元工作流（深度思考）：策略脑构建思维链 → 编排层执行 → 汇总报告。
策略脑根据用户意图规划执行步骤（CoT），编排层动态调用分析脑、生成脑、搜索等模块。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

# 统一接口配置：config.api_config，引用 web_search 接口
from config.search_config import get_search_config
from core.intent.intent_agent import IntentAgent
from core.intent.planning_agent import PlanningAgent
from core.failure_codes import FailureCode
from core.skill_runtime import build_skill_execution_plan, fallback_plugins_for_step
from core.plugin_registry import get_registry
from core.step_descriptions_for_planning import build_available_modules_section
from core.search import WebSearcher
from domain.memory import MemoryService
from models.request import ContentRequest
from services.ai_service import SimpleAIService
from workflows.analysis_brain_subgraph import build_analysis_brain_subgraph
from workflows.generation_brain_subgraph import build_generation_brain_subgraph
from workflows.reasoning_loop import reasoning_loop_node
from workflows.types import (
    MetaState,
    IP_BUILD_PHASE_INTAKE,
    IP_BUILD_PHASE_PLANNED,
    IP_BUILD_PHASE_EXECUTING,
)
from workflows import ip_build_flow

logger = logging.getLogger(__name__)


def _ip_build_plan_ready_message(plan_template_id: str | None, *, variant: str = "intake") -> str:
    """
    刚生成/加载 Plan 时的用户可见文案。
    variant=intake：从 intake 补齐后直通 plan_once；variant=planned：从 planned 进入 plan_once。
    """
    from plans import PLAN_TEMPLATE_DYNAMIC, get_template_meta

    tid = (plan_template_id or "").strip()
    is_dynamic = not tid or tid == PLAN_TEMPLATE_DYNAMIC
    if is_dynamic:
        if variant == "planned":
            return "计划已生成。接下来我会从第一步开始执行。你回复任意一句即可继续。"
        return "信息已补齐，已为你生成执行计划。下一步我将开始执行第一步；你只要回复任意一句继续即可。"
    meta = get_template_meta(tid) or {}
    # 展示名优先用注册时的 name（短标题），其次 description，最后 template_id
    plan_label = (meta.get("name") or meta.get("description") or tid).strip()
    if variant == "planned":
        return f"计划已生成：固定模板「{plan_label}」（模板 ID：{tid}）。接下来我会从第一步开始执行。你回复任意一句即可继续。"
    return f"信息已补齐，已为你加载固定模板计划「{plan_label}」（模板 ID：{tid}）。下一步我将开始执行第一步；你只要回复任意一句继续即可。"


def _append_thinking(state: dict, step_name: str, thought: str) -> list[dict]:
    logs = list(state.get("thinking_logs") or [])
    logs.append({"step": step_name, "thought": thought, "timestamp": datetime.now(timezone.utc).isoformat()})
    return logs


def _parse_user_payload(user_input: Any) -> dict:
    """
    解析用户输入载荷：
    - 优先支持 JSON 字符串（前端/路由层传入 raw_query、conversation_context 等）
    - 若解析失败或不是 JSON，回退为纯文本对话：raw_query=user_input
    """
    if user_input is None:
        return {"raw_query": "", "conversation_context": ""}
    if isinstance(user_input, dict):
        data = dict(user_input)
        data.setdefault("raw_query", "")
        data.setdefault("conversation_context", "")
        return data
    if not isinstance(user_input, str):
        return {"raw_query": str(user_input), "conversation_context": ""}
    text = user_input.strip()
    if not text:
        return {"raw_query": "", "conversation_context": ""}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data.setdefault("raw_query", "")
            data.setdefault("conversation_context", "")
            return data
    except (TypeError, json.JSONDecodeError):
        pass
    return {"raw_query": text, "conversation_context": ""}


def _complete_step_params(step_name: str, params: dict, user_data: dict) -> dict:
    """
    从 user_input 解析出的 user_data 补全某步缺失的关键参数（如 web_search 的 query）。
    仅做规则补全，不调用 LLM；保留插件模式下的「首轮规划为主、执行前轻量补全」。
    """
    if not isinstance(params, dict):
        params = {}
    out = dict(params)
    step = (step_name or "").lower()
    brand = (user_data.get("brand_name") or "").strip()
    product = (user_data.get("product_desc") or "").strip()
    topic = (user_data.get("topic") or "").strip()
    raw_query = (user_data.get("raw_query") or "").strip()
    fallback_query = f"{brand} {product} {topic}".strip() or raw_query or "相关信息"

    if step == "web_search":
        if not (out.get("query") or "").strip():
            out["query"] = raw_query or fallback_query
    elif step == "kb_retrieve":
        if not (out.get("query") or "").strip():
            out["query"] = fallback_query
    return out


def _build_trace_id(session_id: str) -> str:
    """生成跨节点可检索的链路 ID。"""
    sid = (session_id or "no-session").strip()[:24]
    return f"{sid}-{uuid.uuid4().hex[:10]}"


def _trace_event(trace_id: str, **payload: Any) -> None:
    data = {"trace_id": trace_id, **payload}
    try:
        logger.info("trace_event: %s", json.dumps(data, ensure_ascii=False, default=str))
    except Exception:
        logger.info("trace_event: %s", data)


def _ensure_meta_state(state: dict) -> dict:
    return {
        "user_input": state.get("user_input", ""),
        "analysis": state.get("analysis", ""),
        "content": state.get("content", ""),
        "session_id": state.get("session_id", ""),
        "user_id": state.get("user_id", ""),
        "evaluation": state.get("evaluation", {}),
        "need_revision": state.get("need_revision", False),
        "stage_durations": state.get("stage_durations", {}),
        "analyze_cache_hit": state.get("analyze_cache_hit", False),
        "used_tags": state.get("used_tags", []),
        "plan": state.get("plan", []),
        "task_type": state.get("task_type", ""),
        "current_step": state.get("current_step", 0),
        "thinking_logs": state.get("thinking_logs", []),
        "step_outputs": state.get("step_outputs", []),
        "search_context": state.get("search_context", ""),
        "memory_context": state.get("memory_context", ""),
        "kb_context": state.get("kb_context", ""),
        "effective_tags": state.get("effective_tags", []),
        "analysis_plugins": state.get("analysis_plugins", []),
        "generation_plugins": state.get("generation_plugins", []),
        "phase": state.get("phase", ""),
        "ip_context": state.get("ip_context") or {},
        "ip_build_handled": state.get("ip_build_handled", False),
        "pending_questions": state.get("pending_questions") or [],
        "plan_template_id": state.get("plan_template_id", ""),
        "plan_template_name": state.get("plan_template_name", ""),
        "trace_id": state.get("trace_id", ""),
        "failure_code": state.get("failure_code", ""),
        "skill_ab_bucket": state.get("skill_ab_bucket", ""),
    }


def build_meta_workflow(
    ai_service: SimpleAIService | None = None,
    web_searcher: WebSearcher | None = None,
    memory_service: MemoryService | None = None,
    knowledge_port: Any = None,
    metrics: dict | None = None,
    track_duration: Any = None,
) -> Any:
    """
    构建元工作流（深度思考）：
    1. planning_node（策略脑）：构建思维链
    2. orchestration_node（编排层）：按思维链调用模块（含 kb_retrieve、analyze、generate 等；活动策划能力在分析脑/生成脑内）
    3. compilation_node（汇总）：整合结果

    依赖注入：web_searcher、memory_service、knowledge_port 可注入以便测试或替换实现。
    """
    from langgraph.graph import END, StateGraph
    
    ai_svc = ai_service or SimpleAIService()
    if web_searcher is None:
        cfg = get_search_config()
        web_searcher = WebSearcher(
            api_key=cfg.get("baidu_api_key"),
            provider=cfg["provider"],
            base_url=cfg.get("baidu_base_url"),
            top_k=cfg.get("baidu_top_k", 20),
        )
    memory_svc = memory_service or MemoryService()
    # 策略脑需要直接调用 llm，通过门面暴露（避免外部访问 _llm）
    llm = ai_svc._llm  # 门面内部协调，SimpleAIService 与 meta_workflow 同属编排层

    use_metrics = metrics and track_duration is not None

    async def planning_node(state: MetaState) -> dict:
        """
        策略脑：使用 IntentAgent + PlanningAgent 构建思维链
        新架构：意图识别 -> 策略规划 -> 执行计划
        """
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        trace_id = (base.get("trace_id") or "").strip() or _build_trace_id(base.get("session_id", ""))
        user_input = base.get("user_input")
        data = _parse_user_payload(user_input)

        raw_query = (data.get("raw_query") or "").strip()
        conversation_context = (data.get("conversation_context") or "").strip()
        brand = (data.get("brand_name") or "").strip()
        product = (data.get("product_desc") or "").strip()
        topic = (data.get("topic") or "").strip()

        # 初始化 IntentAgent 和 PlanningAgent
        intent_agent = IntentAgent(llm)
        planning_agent = PlanningAgent(llm)

        # 步骤1: 意图识别
        intent_result = await intent_agent.classify_intent(
            user_input=raw_query,
            conversation_context=conversation_context,
        )

        intent = intent_result.get("intent", "free_discussion")
        confidence = intent_result.get("confidence", 0.5)
        intent_notes = intent_result.get("notes", "")
        need_clarification = intent_result.get("need_clarification", False)

        logger.info(
            "intent_step: trace_id=%s recognized intent=%s confidence=%.3f need_clarification=%s raw_query=%r context_len=%d notes=%r",
            trace_id,
            intent,
            float(confidence or 0.0),
            bool(need_clarification),
            raw_query[:120],
            len(conversation_context or ""),
            (intent_notes or "")[:200],
        )
        _trace_event(
            trace_id,
            stage="intent",
            intent=intent,
            confidence=float(confidence or 0.0),
            need_clarification=bool(need_clarification),
        )

        # 如果需要澄清，返回澄清问题
        if need_clarification:
            clarification_question = (intent_result.get("clarification_question") or "").strip() or "你希望我最终给你什么结果：可直接发布的内容，还是先分析再给建议？"
            thought = f"意图识别置信度较低({confidence})，转为自然澄清：{clarification_question}"
            thinking_logs = _append_thinking(base, "意图识别", thought)
            return {
                **base,
                "trace_id": trace_id,
                "plan": [{
                    "step": "casual_reply",
                    "params": {"clarify": True, "clarification_kind": "intent_unclear", "question": clarification_question},
                    "reason": "意图不明确，先自然回应并做最小澄清"
                }],
                "task_type": "clarification",
                "current_step": 0,
                "thinking_logs": thinking_logs,
                "step_outputs": [],
                "analysis_plugins": [],
                "generation_plugins": [],
                "planning_duration_sec": round(time.perf_counter() - t0, 4),
            }

        # 步骤2: 策略规划
        user_data = {
            "brand_name": brand,
            "product_desc": product,
            "topic": topic,
            "platform": data.get("platform", ""),
        }
        plan_result = await planning_agent.plan_steps(
            intent_data=intent_result,
            user_data=user_data,
            conversation_context=conversation_context,
        )

        plan = plan_result.get("steps", [])
        task_type = plan_result.get("task_type", "campaign_or_copy")
        _trace_event(
            trace_id,
            stage="plan",
            task_type=task_type,
            plan_steps=[(s.get("step") or "") for s in plan if isinstance(s, dict)],
        )

        # 提取 plugins 字段到顶层，供编排层使用（LLM 可能返回字符串，规范为列表）
        analysis_plugins = []
        generation_plugins = []
        for step in plan:
            plugins = step.get("plugins", [])
            if isinstance(plugins, str) and plugins.strip():
                plugins = [plugins.strip()]
            elif not isinstance(plugins, list):
                plugins = []
            step_name = step.get("step", "").lower()
            if step_name == "analyze":
                analysis_plugins.extend(plugins)
            elif step_name == "generate":
                generation_plugins.extend(plugins)

        # 兼容旧版格式：添加 params 字段
        for step in plan:
            if "params" not in step:
                step["params"] = {}

        # 记忆兜底：创作/分析类意图若未显式规划 memory_query，则自动注入到首位，
        # 确保后续 analyze/generate 可稳定拿到长期记忆与近期交互摘要。
        if intent in ("generate_content", "strategy_planning", "query_info", "account_diagnosis", "free_discussion"):
            has_memory_step = any((s.get("step", "").lower() == "memory_query") for s in plan if isinstance(s, dict))
            if not has_memory_step:
                plan.insert(0, {"step": "memory_query", "plugins": [], "params": {}, "reason": "记忆兜底：注入长期记忆与近期交互"})
                logger.info("intent_step: trace_id=%s auto-insert memory_query for intent=%s", trace_id, intent)

        # 安全过滤：如果意图不是 generate_content，移除 generate 步骤
        if intent not in ("generate_content", "strategy_planning"):
            plan = [s for s in plan if s.get("step", "").lower() != "generate"]

        # 构建思维链日志
        thought = f"策略脑规划 {len(plan)} 个步骤：" + " → ".join(s.get("step", "") for s in plan)
        thinking_logs = _append_thinking(base, "策略脑规划", thought)
        thinking_logs = _append_thinking({**base, "thinking_logs": thinking_logs}, "意图识别", f"意图={intent}, 置信度={confidence}, 依据={intent_notes[:50]}")

        duration = round(time.perf_counter() - t0, 4)
        logger.info(f"planning_node 完成: task_type={task_type}, steps={len(plan)}, duration={duration}s")

        return {
            **base,
            "trace_id": trace_id,
            "plan": plan,
            "task_type": task_type,
            "current_step": 0,
            "thinking_logs": thinking_logs,
            "step_outputs": [],
            "analysis_plugins": list(set(analysis_plugins)),
            "generation_plugins": list(set(generation_plugins)),
            "planning_duration_sec": duration,
            "intent": intent,
            "intent_confidence": confidence,
        }

    async def orchestration_node(state: MetaState) -> dict:
        """
        编排层：按思维链顺序执行各模块。
        支持：web_search、memory_query、kb_retrieve、bilibili_hotspot、analyze、generate、evaluate。
        活动策划相关能力已移入分析脑与生成脑，此处仅按步骤编排调用。
        """
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        plan = base.get("plan") or []
        user_input_str = base.get("user_input") or ""
        user_id = base.get("user_id") or ""
        session_id = base.get("session_id") or ""

        user_data = _parse_user_payload(user_input_str)
        
        brand = user_data.get("brand_name", "")
        product = user_data.get("product_desc", "")
        topic = user_data.get("topic", "")
        raw_query = user_data.get("raw_query", "")
        tags = user_data.get("tags", [])
        doc_context = user_data.get("session_document_context", "")
        
        # 执行上下文（累积各步结果）
        context = {
            "search_results": "",
            "memory_context": "",
            "kb_context": "",
            "analysis": {},
            "content": "",
            "evaluation": {},
        }
        
        step_outputs = []
        thinking_logs = list(base.get("thinking_logs") or [])

        # 可并行步骤：web_search、memory_query、bilibili_hotspot、kb_retrieve（无依赖）
        PARALLEL_STEPS = {"web_search", "memory_query", "industry_news_bilibili_rankings", "kb_retrieve"}
        parallel_plans = [s for s in plan if (s.get("step") or "").lower() in PARALLEL_STEPS]
        sequential_plans = [s for s in plan if (s.get("step") or "").lower() not in PARALLEL_STEPS]

        # 添加新B站热点获取步骤执行函数
        async def _run_industry_news_bilibili_rankings(sc: dict) -> tuple[dict, str, dict]:
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            plugin_center = getattr(ai_svc._analyzer, "plugin_center", None)
            if plugin_center is None or not plugin_center.has_plugin("industry_news_bilibili_rankings"):
                return ({"step": sn, "reason": reason, "result": {"error": "插件未加载"}}, "插件未加载", {})
            ctx = {**base, "analysis": context.get("analysis", {})}
            res = await plugin_center.get_output("industry_news_bilibili_rankings", ctx)
            plug_analysis = res.get("analysis") or {}
            industry_news = plug_analysis.get("industry_news", "")
            bilibili_rankings = plug_analysis.get("bilibili_multi_rankings", "")
            return (
                {"step": sn, "reason": reason, "result": {"plugin_executed": True}},
                "已获取行业新闻与B站榜单分析",
                {"analysis": {"industry_news": industry_news, "bilibili_multi_rankings": bilibili_rankings}},
            )

        async def _run_web_search(sc: dict) -> tuple[dict, str, dict]:
            sn, params, reason = sc.get("step", ""), sc.get("params") or {}, sc.get("reason", "")
            query = params.get("query") or f"{brand} {product} {topic}".strip()
            results = await web_searcher.search(query, num_results=3)
            txt = web_searcher.format_results_as_context(results)
            return (
                {"step": sn, "reason": reason, "result": {"search_count": len(results), "summary": txt[:200]}},
                f"已搜索「{query}」，获得 {len(results)} 条结果",
                {"search_results": txt},
            )

        async def _run_memory_query(sc: dict) -> tuple[dict, str, dict]:
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            memory = await memory_svc.get_memory_for_analyze(
                user_id=user_id, brand_name=brand, product_desc=product, topic=topic, tags_override=tags
            )
            mc = memory.get("preference_context", "")
            et = memory.get("effective_tags", [])
            return (
                {"step": sn, "reason": reason, "result": {"has_memory": bool(mc)}},
                f"已查询用户记忆，{'有' if mc else '无'}历史偏好",
                {"memory_context": mc, "effective_tags": et},
            )

        async def _run_bilibili_hotspot(sc: dict) -> tuple[dict, str, dict]:
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            plugin_center = getattr(ai_svc._analyzer, "plugin_center", None)
            if plugin_center is None or not plugin_center.has_plugin("bilibili_hotspot"):
                return ({"step": sn, "reason": reason, "result": {"error": "插件未加载"}}, "插件未加载", {})
            ctx = {**base, "analysis": context.get("analysis", {})}
            res = await plugin_center.get_output("bilibili_hotspot", ctx)
            plug_analysis = res.get("analysis") or {}
            hotspot = plug_analysis.get("bilibili_hotspot", "")
            return (
                {"step": sn, "reason": reason, "result": {"plugin_executed": True}},
                "已获取 B站热点报告（缓存）",
                {"analysis": {"bilibili_hotspot": hotspot}},
            )

        async def _run_kb_retrieve(sc: dict) -> tuple[dict, str, dict]:
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            _port = knowledge_port
            if _port is None:
                try:
                    from services.retrieval_service import RetrievalService
                    _port = RetrievalService()
                except Exception:
                    return ({"step": sn, "reason": reason, "result": {"skipped": "no_kb"}}, "未配置知识库，跳过", {})
            query = f"{brand} {product} {topic}".strip() or "营销策略"
            try:
                passages = await _port.retrieve(query, top_k=4)
                txt = "\n\n".join(passages) if passages else ""
            except Exception as e:
                logger.warning("kb_retrieve 失败: %s", e)
                txt = ""
            return (
                {"step": sn, "reason": reason, "result": {"passage_count": len(passages) if passages else 0}},
                f"已检索知识库，获得 {len(passages) if passages else 0} 条相关段落",
                {"kb_context": txt},
            )

        def _step_runner(sc: dict):
            name = (sc.get("step") or "").lower()
            if name == "web_search":
                return _run_web_search(sc)
            if name == "memory_query":
                return _run_memory_query(sc)
            if name == "industry_news_bilibili_rankings":
                return _run_industry_news_bilibili_rankings(sc)
            if name == "kb_retrieve":
                return _run_kb_retrieve(sc)
            return None

        # 并行执行
        if parallel_plans:
            tasks = [_step_runner(sc) for sc in parallel_plans]
            tasks = [t for t in tasks if t is not None]
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                search_parts = []
                for i, r in enumerate(results):
                    if isinstance(r, Exception):
                        logger.warning("并行步骤执行失败: %s", r)
                        continue
                    out, thought, updates = r
                    step_outputs.append(out)
                    thinking_logs = _append_thinking({**base, "thinking_logs": thinking_logs}, out["step"], thought)
                    if "search_results" in updates:
                        search_parts.append(updates["search_results"])
                    if "memory_context" in updates:
                        context["memory_context"] = updates["memory_context"]
                    if "effective_tags" in updates:
                        context["effective_tags"] = updates["effective_tags"]
                    if "analysis" in updates:
                        existing = context.get("analysis") or {}
                        context["analysis"] = {**existing, **updates["analysis"]}
                    if "kb_context" in updates:
                        context["kb_context"] = updates["kb_context"]
                if search_parts:
                    context["search_results"] = "\n\n".join(search_parts)
                    
        # 闲聊短路：如果 plan 中只有 casual_reply，直接跳过后续 sequential 循环的 analyze/generate 逻辑
        if len(plan) == 1 and plan[0].get("step") == "casual_reply":
            # 注入当前日期时间，便于回答「当前时间」「今天几号」「明天是哪天」
            from datetime import timedelta
            _now_utc = datetime.now(timezone.utc)
            _cn = _now_utc + timedelta(hours=8)
            _weekday_cn = ["一", "二", "三", "四", "五", "六", "日"]
            _dt_str = _cn.strftime(f"%Y年%m月%d日 %H:%M 星期{_weekday_cn[_cn.weekday()]}")
            casual_sys = f"""你是专业的营销AI助手。以自然、亲切、专业的口吻回复用户的闲聊（如问候、感谢等）。保持简短，引导用户进行营销相关的创作或分析。不要进行长篇大论。
【参考·当前日期与时间】{_dt_str}。仅当用户明确问「当前时间」「今天几号」「明天是哪天」等时，才用上述日期回答；其他问题（问候、营销、一般闲聊）正常回复，不要主动报日期。"""
            try:
                # 使用简单的 LLM 调用生成回复
                from langchain_core.messages import SystemMessage, HumanMessage
                reply_res = await llm.ainvoke([
                    SystemMessage(content=casual_sys),
                    HumanMessage(content=user_input_str)
                ])
                reply_text = reply_res.content
            except Exception as e:
                logger.warning("闲聊回复生成失败: %s", e)
                reply_text = "你好！有什么我可以帮你的吗？"

            context["content"] = reply_text
            step_outputs.append({"step": "casual_reply", "reason": plan[0].get("reason"), "result": {"reply": reply_text}})
            thinking_logs = _append_thinking({**base, "thinking_logs": thinking_logs}, "casual_reply", "已生成闲聊回复")
            
            sequential_plans = [] # 清空后续计划

        # 顺序执行其余步骤
        for i, step_config in enumerate(plan):
            step_name = step_config.get("step")
            params = step_config.get("params") or step_config.get("parameters") or {}
            reason = step_config.get("reason", "")
            
            logger.info("编排层执行步骤 %d/%d: %s", i+1, len(plan), step_name)
            
            try:
                if step_name == "web_search":
                    query = params.get("query") or f"{brand} {product} {topic}".strip()
                    search_results = await web_searcher.search(query, num_results=5)
                    context["search_results"] = web_searcher.format_results_as_context(search_results)
                    step_outputs.append({
                        "step": step_name,
                        "reason": reason,
                        "result": {"search_count": len(search_results), "summary": context["search_results"][:200]},
                    })
                    thinking_logs = _append_thinking(
                        {**base, "thinking_logs": thinking_logs},
                        step_name,
                        f"已搜索「{query}」，获得 {len(search_results)} 条结果",
                    )
                
                elif step_name == "memory_query":
                    memory = await memory_svc.get_memory_for_analyze(
                        user_id=user_id,
                        brand_name=brand,
                        product_desc=product,
                        topic=topic,
                        tags_override=tags if tags else None,
                    )
                    context["memory_context"] = memory.get("preference_context", "")
                    context["effective_tags"] = memory.get("effective_tags", [])
                    step_outputs.append({
                        "step": step_name,
                        "reason": reason,
                        "result": {"has_memory": bool(context["memory_context"])},
                    })
                    thinking_logs = _append_thinking(
                        {**base, "thinking_logs": thinking_logs},
                        step_name,
                        f"已查询用户记忆，{'有' if context['memory_context'] else '无'}历史偏好",
                    )
                
                elif step_name == "analyze":
                    request = ContentRequest(
                        user_id=user_id,
                        brand_name=brand,
                        product_desc=product,
                        topic=topic,
                        tags=tags,
                    )
                    # 分析时可引用搜索结果、记忆、知识库检索
                    preference_ctx = context.get("memory_context") or None
                    if context.get("search_results"):
                        if preference_ctx:
                            preference_ctx += f"\n\n【网络检索信息】\n{context['search_results']}"
                        else:
                            preference_ctx = f"【网络检索信息】\n{context['search_results']}"
                    if context.get("kb_context"):
                        preference_ctx = (preference_ctx or "") + "\n\n【知识库检索】\n" + context["kb_context"]
                    # 「根据检索结果回答」时走 answer_from_search，直接回答用户问题，不输出推广策略
                    reason_lower = (reason or "").lower()
                    answer_from_search = "根据检索结果" in reason_lower and bool(context.get("search_results"))
                    plan_has_generate = any((s.get("step") or "").lower() == "generate" for s in plan)
                    
                    # 优先从步骤参数获取插件列表，其次从全局状态获取
                    step_plugins = params.get("analysis_plugins")
                    if isinstance(step_plugins, str):
                        step_plugins = [step_plugins]
                    analysis_plugins = step_plugins or base.get("analysis_plugins") or []
                    
                    plugin_input = {k: v for k, v in user_data.items() if k not in ("brand_name", "product_desc", "topic", "tags")}
                    if answer_from_search and raw_query:
                        plugin_input = dict(plugin_input or {})
                        plugin_input["raw_query"] = raw_query
                    plugin_input = plugin_input if plugin_input else None
                    analysis_result, cache_hit = await ai_svc.analyze(
                        request,
                        preference_context=preference_ctx,
                        context_fingerprint={"tags": context.get("effective_tags", []), "analysis_plugins": sorted(analysis_plugins)},
                        answer_from_search=answer_from_search,
                        analysis_plugins=analysis_plugins if not answer_from_search else None,
                        plugin_input=plugin_input,
                    )
                    # 合并分析结果，保留插件写入的字段（如 bilibili_hotspot）
                    existing_analysis = context.get("analysis") or {}
                    merged = dict(analysis_result) if isinstance(analysis_result, dict) else {}
                    if isinstance(existing_analysis, dict):
                        for k, v in existing_analysis.items():
                            if k not in merged:
                                merged[k] = v
                    context["analysis"] = merged
                    context["analyze_cache_hit"] = cache_hit
                    step_outputs.append({
                        "step": step_name,
                        "reason": reason,
                        "result": {
                            "semantic_score": analysis_result.get("semantic_score", 0),
                            "angle": analysis_result.get("angle", ""),
                        },
                    })
                    thought = "已根据检索结果回答" if answer_from_search else f"分析完成，关联度 {analysis_result.get('semantic_score', 0)}，切入点：{analysis_result.get('angle', '')}"
                    thinking_logs = _append_thinking(
                        {**base, "thinking_logs": thinking_logs},
                        step_name,
                        thought,
                    )
                    # 无 generate 步骤时，若为本轮「根据检索结果回答」，将分析结论作为最终回复正文
                    if answer_from_search and not plan_has_generate:
                        context["content"] = (analysis_result.get("angle") or "").strip() or context.get("content", "")

                elif step_name == "generate":
                    platform = params.get("platform", "")
                    output_type = params.get("output_type", "text")
                    if platform:
                        topic_with_platform = f"{topic} {platform}".strip()
                    else:
                        topic_with_platform = topic
                    generation_plugins = base.get("generation_plugins") or []
                    memory_ctx = context.get("memory_context", "")
                    analysis_for_generate = dict(context.get("analysis", {}))
                    analysis_for_generate.setdefault("brand_name", brand)
                    analysis_for_generate.setdefault("product_desc", product)
                    generated = await ai_svc.generate(
                        analysis_for_generate,
                        topic=topic_with_platform,
                        raw_query=raw_query,
                        session_document_context=doc_context,
                        output_type=output_type,
                        generation_plugins=generation_plugins,
                        memory_context=memory_ctx,
                    )
                    context["content"] = generated
                    step_outputs.append({
                        "step": step_name,
                        "reason": reason,
                        "result": {"content_length": len(generated), "preview": generated[:150]},
                    })
                    thinking_logs = _append_thinking(
                        {**base, "thinking_logs": thinking_logs},
                        step_name,
                        f"已生成内容，长度 {len(generated)} 字符",
                    )
                
                elif step_name == "evaluate":
                    steps_used = "、".join((s.get("step") or "") for s in plan if s.get("step"))
                    eval_context = {
                        "brand_name": brand,
                        "topic": topic,
                        "analysis": context.get("analysis", {}),
                        "steps_used": steps_used or "未提供",
                    }
                    evaluation = await ai_svc.evaluate_content(context.get("content", ""), eval_context)
                    context["evaluation"] = evaluation
                    context["need_revision"] = evaluation.get("overall_score", 0) < 6
                    step_outputs.append({
                        "step": step_name,
                        "reason": reason,
                        "result": {
                            "overall_score": evaluation.get("overall_score", 0),
                            "suggestions": evaluation.get("suggestions", ""),
                        },
                    })
                    thinking_logs = _append_thinking(
                        {**base, "thinking_logs": thinking_logs},
                        step_name,
                        f"评估完成，综合分 {evaluation.get('overall_score', 0)}，{'需修订' if context['need_revision'] else '通过'}",
                    )
                
                else:
                    # 插件步骤：尝试从 PluginRegistry 获取并执行
                    plugin_wf = get_registry().get_workflow(step_name)
                    if plugin_wf is not None:
                        plugin_state = {
                            **base,
                            "analysis": context.get("analysis", base.get("analysis")),
                            "content": context.get("content", base.get("content")),
                            "evaluation": context.get("evaluation", base.get("evaluation")),
                            "need_revision": context.get("need_revision", base.get("need_revision")),
                            "analyze_cache_hit": context.get("analyze_cache_hit", base.get("analyze_cache_hit")),
                            "used_tags": context.get("effective_tags", base.get("used_tags", [])),
                        }
                        try:
                            plugin_result = await plugin_wf.ainvoke(plugin_state)
                            if isinstance(plugin_result, dict):
                                if "analysis" in plugin_result and plugin_result["analysis"]:
                                    # 合并插件 analysis，保留已有字段（如 analyze 的 semantic_score 等）
                                    existing = context.get("analysis") or {}
                                    plug = plugin_result["analysis"]
                                    if isinstance(existing, dict) and isinstance(plug, dict):
                                        merged = {**existing, **plug}
                                        context["analysis"] = merged
                                    else:
                                        context["analysis"] = plug
                                if "content" in plugin_result and plugin_result["content"]:
                                    context["content"] = plugin_result["content"]
                                if "used_tags" in plugin_result:
                                    context["effective_tags"] = plugin_result.get("used_tags", [])
                            step_outputs.append({
                                "step": step_name,
                                "reason": reason,
                                "result": {"plugin_executed": True},
                            })
                            thinking_logs = _append_thinking(
                                {**base, "thinking_logs": thinking_logs},
                                step_name,
                                f"已执行插件步骤: {step_name}",
                            )
                        except Exception as pe:
                            logger.warning("插件 %s 执行失败: %s", step_name, pe, exc_info=True)
                            step_outputs.append({
                                "step": step_name,
                                "reason": reason,
                                "result": {"error": str(pe)},
                            })
                            thinking_logs = _append_thinking(
                                {**base, "thinking_logs": thinking_logs},
                                step_name,
                                f"执行失败：{pe}",
                            )
                    else:
                        logger.warning("未知步骤类型且无对应插件: %s", step_name)
                        step_outputs.append({
                            "step": step_name,
                            "reason": reason,
                            "result": {"error": f"未知模块: {step_name}，请注册对应插件或使用内置步骤"},
                        })
            
            except Exception as e:
                logger.warning("步骤 %s 执行失败: %s", step_name, e, exc_info=True)
                step_outputs.append({
                    "step": step_name,
                    "reason": reason,
                    "result": {"error": str(e)},
                })
                thinking_logs = _append_thinking(
                    {**base, "thinking_logs": thinking_logs},
                    step_name,
                    f"执行失败：{e}",
                )
        
        duration = round(time.perf_counter() - t0, 4)
        return {
            **base,
            "analysis": context.get("analysis", base.get("analysis", "")),
            "content": context.get("content", base.get("content", "")),
            "evaluation": context.get("evaluation", base.get("evaluation", {})),
            "need_revision": context.get("need_revision", False),
            "analyze_cache_hit": context.get("analyze_cache_hit", False),
            "used_tags": context.get("effective_tags", base.get("used_tags", [])),
            "search_context": context.get("search_results", ""),
            "memory_context": context.get("memory_context", ""),
            "current_step": len(plan),
            "thinking_logs": thinking_logs,
            "step_outputs": step_outputs,
            "orchestration_duration_sec": duration,
        }

    async def compilation_node(state: MetaState) -> dict:
        """汇总：整合思考过程与各步输出，生成 DeepSeek 风格的叙述式思维链与最终报告。闲聊路径也输出思维链+输出+建议引导，方便调试和展示。"""
        from workflows.thinking_narrative import generate_thinking_narrative
        import os
        
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        plan = base.get("plan") or []
        base["used_tags"] = base.get("effective_tags") or base.get("used_tags") or []
        step_outputs = base.get("step_outputs") or []
        thinking_logs = base.get("thinking_logs") or []
        user_input_str = base.get("user_input") or ""
        search_context = base.get("search_context") or ""
        analysis = base.get("analysis") or {}
        
        # 默认使用 LLM 思维链叙述；设 USE_SIMPLE_THINKING_NARRATIVE=1 可改为步骤拼接以节省时间
        use_simple_narrative = os.environ.get("USE_SIMPLE_THINKING_NARRATIVE", "0").strip().lower() in ("1", "true", "yes")
        used_tags = base.get("used_tags") or []
        thinking_narrative = ""
        if use_simple_narrative:
            for entry in thinking_logs:
                thinking_narrative += f"- **{entry.get('step', '')}**: {entry.get('thought', '')}\n"
            thinking_narrative = thinking_narrative.strip() or "（无）"
        else:
            try:
                t0_nar = time.perf_counter()
                thinking_narrative = await generate_thinking_narrative(
                    user_input_str=user_input_str,
                    thinking_logs=thinking_logs,
                    step_outputs=step_outputs,
                    search_context=search_context,
                    analysis=analysis,
                    llm_client=llm,
                    effective_tags=used_tags,
                )
                duration_nar = round(time.perf_counter() - t0_nar, 2)
                logger.info("思维链叙述(thinking_narrative) 耗时 %.2fs（模型见 config.thinking_narrative，默认 qwen-turbo）", duration_nar)
            except Exception as e:
                logger.warning("思考叙述生成失败，使用步骤列表: %s", e)
                for entry in thinking_logs:
                    thinking_narrative += f"- **{entry.get('step', '')}**: {entry.get('thought', '')}\n"
        
        thinking_narrative_str = (thinking_narrative.strip() or "（无）")
        final_content = (base.get("content") or "").strip()
        # 避免将内部错误文案直接暴露给用户（如无可用生成插件）
        if final_content and ("无可用生成插件" in final_content or "未返回内容" in final_content):
            final_content = ""
        if final_content:
            output_str = final_content
        else:
            # 无生成步骤时（如仅做策略分析、竞品分析），以分析结果作为输出
            analysis_obj = base.get("analysis") or {}
            
            # 特殊处理：账号诊断报告格式化
            diagnosis_report = analysis_obj.get("account_diagnosis") if isinstance(analysis_obj, dict) else None
            
            if diagnosis_report and isinstance(diagnosis_report, dict):
                # 提取数据
                summary = diagnosis_report.get("summary", "暂无")
                basic = diagnosis_report.get("basic_info", {})
                metrics = diagnosis_report.get("metrics", {})
                issues = diagnosis_report.get("issues", [])
                suggestions = diagnosis_report.get("suggestions", [])
                
                # 格式化基础数据
                fans = basic.get("fans", 0)
                works = basic.get("works_count", 0)
                like_rate = metrics.get("like_rate", 0)
                
                # 格式化诊断问题
                issues_str = ""
                if issues:
                    for issue in issues:
                        indicator = issue.get("indicator", "未命名指标")
                        msg = issue.get("msg", "") or issue.get("value", "")
                        issues_str += f" - {indicator} : {msg}\n"
                else:
                    issues_str = " - 暂无明显问题\n"
                
                # 格式化策略建议
                suggestions_str = ""
                if suggestions:
                    for sug in suggestions:
                        cat = sug.get("category", "通用")
                        content = sug.get("suggestion", "")
                        suggestions_str += f" - {cat} : {content}\n"
                else:
                    suggestions_str = " - 暂无建议\n"

                output_str = f"""- 账号概况 (Summary) : 
  "{summary}" 
 - 基础数据 (Basic Info) : 
 - 粉丝数 : 约 {fans}
 - 作品数 : 约 {works} 个
 - 互动率 : {like_rate}% (基于抓取的近期作品计算) 
 - AI 诊断问题 (Issues) : 
{issues_str}
 - 策略建议 (Suggestions) : 
{suggestions_str}"""

            elif isinstance(analysis_obj, dict) and analysis_obj:
                angle = analysis_obj.get("angle", "")
                reason = analysis_obj.get("reason", "")
                output_str = (angle or "") + "\n\n" + (reason or "") if (angle or reason) else ""
            elif isinstance(analysis_obj, str) and analysis_obj.strip():
                output_str = analysis_obj.strip()
            else:
                output_str = "当前暂时无法生成内容，请稍后再试或换一种方式描述需求。"

        evaluation_str = ""
        evaluation = base.get("evaluation", {})
        if evaluation and not evaluation.get("evaluation_failed"):
            eval_parts = [f"- 综合分：{evaluation.get('overall_score', 0)}/10"]
            quality_assessment = (evaluation.get("quality_assessment") or evaluation.get("suggestions") or "").strip()
            if quality_assessment:
                eval_parts.append(f"- 质量评估：{quality_assessment}")
            evaluation_str = "\n".join(eval_parts)

        suggestion_str = ""
        suggested_next_plan = None
        # 纯闲聊场景跳过后续建议生成，避免重复回复
        is_casual_reply = len(plan) == 1 and plan[0].get("step") == "casual_reply"

        # 闲聊场景下，强制清空思维链叙述，避免与直接回复内容重复（用户感觉啰嗦）
        if is_casual_reply:
            thinking_narrative = ""
            thinking_narrative_str = ""
        
        if not is_casual_reply:
            try:
                from workflows.follow_up_suggestion import get_follow_up_suggestion
                user_data = _parse_user_payload(user_input_str)
                intent = (user_data.get("intent") or "").strip()
                # plan 变量在上文已定义
                suggestion, suggested_step = await get_follow_up_suggestion(
                    user_input_str=user_input_str,
                    intent=intent,
                    plan=plan,
                    step_outputs=step_outputs,
                    content_preview=(final_content or "")[:500],
                )
                if suggestion and suggestion.strip():
                    suggestion_clean = suggestion.strip()
                    if suggestion_clean.startswith("专家建议："):
                        suggestion_clean = suggestion_clean[len("专家建议：") :].strip()
                    if suggestion_clean.startswith("引导句："):
                        suggestion_clean = suggestion_clean[len("引导句：") :].strip()
                    suggestion_str = suggestion_clean
                    if suggested_step in ("generate", "analyze"):
                        suggested_next_plan = [{"step": suggested_step, "params": {}, "reason": "用户采纳后续建议"}]
            except Exception as e:
                logger.debug("后续建议跳过: %s", e)

        # 只反馈最终回复：不将叙述式思维链写入用户可见的 content
        report_parts = [output_str]
        if evaluation_str:
            report_parts.append(evaluation_str)
        if suggestion_str:
            report_parts.append(suggestion_str)
        compiled = "\n\n".join(p for p in report_parts if p).strip()
        thought = f"已整合 {len(step_outputs)} 个步骤的结果，生成最终报告"
        thinking_logs_final = _append_thinking(base, "汇总", thought)
        duration = round(time.perf_counter() - t0, 4)
        logger.info("compilation_node 完成, duration=%.2fs, use_simple_narrative=%s", duration, use_simple_narrative)
        content_sections = {
            "thinking_narrative": thinking_narrative_str,
            "output": output_str,
            "evaluation": evaluation_str,
            "suggestion": suggestion_str,
        }
        out = {
            **base,
            "content": compiled,
            "content_sections": content_sections,
            "thinking_logs": thinking_logs_final,
            "compilation_duration_sec": duration,
        }
        _trace_event(
            (base.get("trace_id") or "").strip() or _build_trace_id(base.get("session_id", "")),
            stage="final",
            failure_code=base.get("failure_code", ""),
            skill_ab_bucket=base.get("skill_ab_bucket", ""),
            evaluation_score=(evaluation or {}).get("overall_score", None),
            interrupted=bool(base.get("__interrupt__", False)),
        )
        if suggested_next_plan is not None:
            out["suggested_next_plan"] = suggested_next_plan
        return out

    # ----- 调度与编排节点（多脑协同 + 动态闭环）-----
    PARALLEL_STEPS = {"web_search", "memory_query", "industry_news_bilibili_rankings", "kb_retrieve"}

    async def _request_remedial_steps(
        parallel_plans: list,
        step_outputs: list,
        has_failure: bool,
        search_empty: bool,
        user_data: dict,
    ) -> list[dict]:
        """
        当并行步骤部分失败或检索结果为空时，请求 LLM 给出 1～2 步补救步骤（如换 query 的 web_search）。
        仅允许 web_search 或 skip，返回 [{"step": "...", "params": {...}, "reason": "..."}, ...]。
        """
        steps_desc = "、".join((s.get("step") or "") for s in parallel_plans)
        outputs_desc = "; ".join(
            (o.get("step") or "") + ":" + str((o.get("result") or {}).get("search_count", (o.get("result") or {}).get("error", "")))
            for o in step_outputs[-len(parallel_plans):]
        )
        raw_query = (user_data.get("raw_query") or "").strip()
        brand = (user_data.get("brand_name") or "").strip()
        topic = (user_data.get("topic") or "").strip()
        prompt = f"""当前并行步骤执行情况：
- 计划步骤：{steps_desc}
- 本轮输出摘要：{outputs_desc}
- 检索结果为空：{search_empty}；存在执行失败：{has_failure}

用户原始问题/品牌/话题：{raw_query or brand or topic or "未提供"}

请给出 1～2 步补救步骤，仅限 step 为 web_search（换一个搜索关键词）或 skip（放弃补救）。输出 JSON 数组，每项含 "step"、"params"（web_search 时需 "query"）、"reason"。若无需补救则输出 []。
示例：[{{"step": "web_search", "params": {{"query": "替代关键词"}}, "reason": "补救：换关键词重试"}}]
直接输出 JSON，不要 markdown 代码块。"""
        try:
            messages = [HumanMessage(content=prompt)]
            response = await llm.invoke(messages, task_type="planning", complexity="low")
            raw = (response or "").strip()
            for prefix in ("```json", "```"):
                if raw.startswith(prefix):
                    raw = raw[len(prefix):].strip()
            if raw.endswith("```"):
                raw = raw[:raw.rfind("```")].strip()
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                return []
            allowed = {"web_search", "skip"}
            return [
                s for s in parsed[:2]
                if isinstance(s, dict) and (s.get("step") or "").lower() in allowed
            ]
        except Exception as e:
            logger.warning("补救步骤请求失败: %s", e)
            return []

    def _router_next(state: MetaState) -> str:
        """调度：根据 plan 与 current_step 决定下一节点。"""
        base = _ensure_meta_state(state)
        trace_id = (base.get("trace_id") or "").strip() or _build_trace_id(base.get("session_id", ""))
        plan = base.get("plan") or []
        current = base.get("current_step") or 0
        if current >= len(plan):
            _trace_event(trace_id, stage="router", current_step=current, action="compilation")
            return "compilation"
        step = (plan[current].get("step") or "").lower()
        plugins = plan[current].get("plugins") or []
        _trace_event(trace_id, stage="router", current_step=current, step=step, plugins=plugins)
        if step in PARALLEL_STEPS:
            return "parallel_retrieval"
        if step == "analyze":
            return "analyze"
        if step == "generate":
            return "generate"
        if step == "evaluate":
            return "evaluate"
        if step == "casual_reply":
            return "casual_reply"
        return "skip"

    async def parallel_retrieval_node(state: MetaState) -> dict:
        """并行检索：执行 plan 中从 current_step 起所有连续并行步，合并结果并推进 current_step。"""
        t0_par = time.perf_counter()
        base = _ensure_meta_state(state)
        trace_id = (base.get("trace_id") or "").strip() or _build_trace_id(base.get("session_id", ""))
        plan = base.get("plan") or []
        current = base.get("current_step") or 0
        parallel_plans = []
        i = current
        while i < len(plan) and (plan[i].get("step") or "").lower() in PARALLEL_STEPS:
            parallel_plans.append(plan[i])
            i += 1
        if not parallel_plans:
            return {**base, "current_step": i}
        user_input_str = base.get("user_input") or ""
        try:
            user_data = json.loads(user_input_str) if isinstance(user_input_str, str) else {}
        except (TypeError, json.JSONDecodeError):
            user_data = {}
        brand = user_data.get("brand_name", "")
        product = user_data.get("product_desc", "")
        topic = user_data.get("topic", "")
        tags = user_data.get("tags", [])
        step_outputs = list(base.get("step_outputs") or [])
        thinking_logs = list(base.get("thinking_logs") or [])
        search_parts = []
        memory_context = base.get("memory_context", "")
        effective_tags = list(base.get("effective_tags") or [])
        kb_context = base.get("kb_context", "")
        analysis_merged = dict(base.get("analysis") or {}) if isinstance(base.get("analysis"), dict) else {}

        async def _run_web_search(sc: dict) -> tuple[dict, str, dict]:
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            params = _complete_step_params("web_search", sc.get("params") or {}, user_data)
            query = (params.get("query") or "").strip() or f"{brand} {product} {topic}".strip()
            try:
                results = await web_searcher.search(query, num_results=3)
                txt = web_searcher.format_results_as_context(results)
                _trace_event(
                    trace_id,
                    stage="step",
                    step="web_search",
                    result="ok",
                    query=query[:120],
                    search_count=len(results or []),
                )
                return (
                    {"step": sn, "reason": reason, "result": {"search_count": len(results), "summary": txt[:200]}},
                    f"已搜索「{query}」，获得 {len(results)} 条结果",
                    {"search_results": txt},
                )
            except Exception as e:
                _trace_event(
                    trace_id,
                    stage="step",
                    step="web_search",
                    result="error",
                    failure_code=FailureCode.WEB_SEARCH_FAILED.value,
                    query=query[:120],
                    error=str(e)[:200],
                )
                return (
                    {
                        "step": sn,
                        "reason": reason,
                        "result": {
                            "search_count": 0,
                            "error": str(e)[:120],
                            "failure_code": FailureCode.WEB_SEARCH_FAILED.value,
                        },
                    },
                    "检索失败，已跳过本步并继续后续步骤",
                    {},
                )

        async def _run_memory_query(sc: dict) -> tuple[dict, str, dict]:
            """MemoryService 为唯一记忆源：三层记忆（品牌事实、用户画像、近期交互）"""
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            try:
                memory = await memory_svc.get_memory_for_analyze(
                    user_id=base.get("user_id", ""),
                    brand_name=brand,
                    product_desc=product,
                    topic=topic,
                    tags_override=tags,
                )
                mc = memory.get("preference_context", "")
                et = memory.get("effective_tags", [])
                _trace_event(
                    trace_id,
                    stage="step",
                    step="memory_query",
                    result="ok",
                    has_memory=bool(mc),
                    memory_len=len(mc or ""),
                    effective_tags=len(et or []),
                )
                return (
                    {"step": sn, "reason": reason, "result": {"has_memory": bool(mc)}},
                    f"已查询用户记忆，{'有' if mc else '无'}历史偏好",
                    {"memory_context": mc, "effective_tags": et},
                )
            except Exception as e:
                _trace_event(
                    trace_id,
                    stage="step",
                    step="memory_query",
                    result="error",
                    error=str(e)[:200],
                    failure_code=FailureCode.MEMORY_QUERY_FAILED.value,
                )
                return (
                    {"step": sn, "reason": reason, "result": {"has_memory": False, "error": str(e)[:120]}},
                    "记忆查询失败，已跳过本步并继续执行后续步骤",
                    {},
                )

        async def _run_bilibili_hotspot(sc: dict) -> tuple[dict, str, dict]:
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            plugin_center = getattr(ai_svc._analyzer, "plugin_center", None)
            if not plugin_center or not plugin_center.has_plugin("bilibili_hotspot"):
                return ({"step": sn, "reason": reason, "result": {"error": "插件未加载"}}, "插件未加载", {})
            ctx = {**base, "analysis": analysis_merged}
            res = await plugin_center.get_output("bilibili_hotspot", ctx)
            plug_analysis = res.get("analysis") or {}
            hotspot = plug_analysis.get("bilibili_hotspot", "")
            return ({"step": sn, "reason": reason, "result": {"plugin_executed": True}}, "已获取 B站热点报告（缓存）", {"analysis": {"bilibili_hotspot": hotspot}})

        # 添加新的B站热点获取执行函数
        async def _run_industry_news_bilibili_rankings(sc: dict) -> tuple[dict, str, dict]:
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            plugin_center = getattr(ai_svc._analyzer, "plugin_center", None)
            if not plugin_center or not plugin_center.has_plugin("industry_news_bilibili_rankings"):
                return ({"step": sn, "reason": reason, "result": {"error": "插件未加载"}}, "插件未加载", {})
            ctx = {**base, "analysis": analysis_merged}
            res = await plugin_center.get_output("industry_news_bilibili_rankings", ctx)
            plug_analysis = res.get("analysis") or {}
            industry_news = plug_analysis.get("industry_news", "")
            bilibili_rankings = plug_analysis.get("bilibili_multi_rankings", "")
            return ({"step": sn, "reason": reason, "result": {"plugin_executed": True}}, "已获取行业新闻与B站榜单分析",
                    {"analysis": {"industry_news": industry_news, "bilibili_multi_rankings": bilibili_rankings}})

        async def _run_kb_retrieve(sc: dict) -> tuple[dict, str, dict]:
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            params = _complete_step_params("kb_retrieve", sc.get("params") or {}, user_data)
            _port = knowledge_port
            if _port is None:
                try:
                    from services.retrieval_service import RetrievalService
                    _port = RetrievalService()
                except Exception:
                    _trace_event(
                        trace_id,
                        stage="step",
                        step="kb_retrieve",
                        result="error",
                        failure_code=FailureCode.KB_RETRIEVE_FAILED.value,
                        error="no_kb",
                    )
                    return ({"step": sn, "reason": reason, "result": {"skipped": "no_kb"}}, "未配置知识库，跳过", {})
            query = (params.get("query") or "").strip() or f"{brand} {product} {topic}".strip() or "营销策略"
            try:
                passages = await _port.retrieve(query, top_k=4)
                txt = "\n\n".join(passages) if passages else ""
                _trace_event(
                    trace_id,
                    stage="step",
                    step="kb_retrieve",
                    result="ok",
                    query=query[:120],
                    passage_count=len(passages or []),
                )
            except Exception as e:
                logger.warning("kb_retrieve 失败: %s", e)
                _trace_event(
                    trace_id,
                    stage="step",
                    step="kb_retrieve",
                    result="error",
                    query=query[:120],
                    failure_code=FailureCode.KB_RETRIEVE_FAILED.value,
                    error=str(e)[:200],
                )
                txt = ""
                passages = []
            return ({"step": sn, "reason": reason, "result": {"passage_count": len(passages) if passages else 0}}, f"已检索知识库，获得 {len(passages) if passages else 0} 条相关段落", {"kb_context": txt})

        def _step_runner(sc: dict):
            name = (sc.get("step") or "").lower()
            if name == "web_search":
                return _run_web_search(sc)
            if name == "memory_query":
                return _run_memory_query(sc)
            if name == "industry_news_bilibili_rankings":
                return _run_industry_news_bilibili_rankings(sc)
            if name == "kb_retrieve":
                return _run_kb_retrieve(sc)
            return None

        tasks = [_step_runner(sc) for sc in parallel_plans]
        tasks = [t for t in tasks if t is not None]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            has_failure = any(isinstance(r, Exception) for r in results)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("并行步骤执行失败: %s", r)
                    continue
                out, thought, updates = r
                step_outputs.append(out)
                thinking_logs = _append_thinking({**base, "thinking_logs": thinking_logs}, out["step"], thought)
                if "search_results" in updates:
                    search_parts.append(updates["search_results"])
                if "memory_context" in updates:
                    memory_context = updates["memory_context"]
                if "effective_tags" in updates:
                    effective_tags = updates["effective_tags"]
                if "analysis" in updates:
                    analysis_merged = {**analysis_merged, **updates["analysis"]}
                if "kb_context" in updates:
                    kb_context = updates["kb_context"]

            # 失败/空结果时的补救：仅做一轮，避免无限循环
            search_empty = not search_parts and any((p.get("step") or "").lower() == "web_search" for p in parallel_plans)
            remedial_enabled = user_data.get("remedial_on_empty", True)
            if remedial_enabled and (has_failure or search_empty):
                remedial_steps = await _request_remedial_steps(
                    parallel_plans, step_outputs, has_failure, search_empty, user_data
                )
                if remedial_steps:
                    thinking_logs = _append_thinking(
                        {**base, "thinking_logs": thinking_logs},
                        "补救规划",
                        f"本轮检索失败或为空，执行 {len(remedial_steps)} 步补救",
                    )
                    remedial_tasks = [_step_runner(s) for s in remedial_steps]
                    remedial_tasks = [t for t in remedial_tasks if t is not None]
                    if remedial_tasks:
                        remedial_results = await asyncio.gather(*remedial_tasks, return_exceptions=True)
                        for r in remedial_results:
                            if isinstance(r, Exception):
                                logger.warning("补救步骤执行失败: %s", r)
                                continue
                            out, thought, updates = r
                            step_outputs.append(out)
                            thinking_logs = _append_thinking({**base, "thinking_logs": thinking_logs}, out["step"], thought)
                            if "search_results" in updates:
                                search_parts.append(updates["search_results"])
                            if "memory_context" in updates:
                                memory_context = updates["memory_context"]
                            if "effective_tags" in updates:
                                effective_tags = updates["effective_tags"]
                            if "kb_context" in updates:
                                kb_context = updates["kb_context"]

        search_context = "\n\n".join(search_parts) if search_parts else ""
        duration_par = round(time.perf_counter() - t0_par, 4)
        logger.info("trace_chain: trace_id=%s step=parallel_retrieval done duration=%.2fs steps=%d", trace_id, duration_par, len(parallel_plans))
        return {
            **base,
            "trace_id": trace_id,
            "search_context": search_context,
            "memory_context": memory_context,
            "effective_tags": effective_tags,
            "kb_context": kb_context,
            "analysis": analysis_merged,
            "step_outputs": step_outputs,
            "thinking_logs": thinking_logs,
            "current_step": i,
        }

    analysis_subgraph = build_analysis_brain_subgraph(ai_svc)
    generation_subgraph = build_generation_brain_subgraph(ai_svc)

    async def analyze_node(state: MetaState) -> dict:
        t0_ana = time.perf_counter()

        # 当前步骤的插件：优先用 plan 中该步的 plugins（Planning Agent 输出），其次用 params.analysis_plugins，再次用 state 已汇总的 analysis_plugins
        base = _ensure_meta_state(state)
        trace_id = (base.get("trace_id") or "").strip() or _build_trace_id(base.get("session_id", ""))
        plan = base.get("plan") or []
        current = base.get("current_step") or 0
        analysis_plugins = list(base.get("analysis_plugins") or [])
        if current < len(plan):
            step_config = plan[current]
            step_plugins = step_config.get("plugins") or []
            if step_plugins:
                analysis_plugins = step_plugins if isinstance(step_plugins, list) else [step_plugins]
            else:
                params = step_config.get("params") or step_config.get("parameters") or {}
                from_params = params.get("analysis_plugins") or []
                if from_params:
                    analysis_plugins = from_params if isinstance(from_params, list) else [from_params]

        runtime_plan = build_skill_execution_plan(analysis_plugins, user_id=base.get("user_id", ""))
        primary_plugins = runtime_plan.get("resolved_plugins") or analysis_plugins
        fallback_plugins = fallback_plugins_for_step("analyze", primary_plugins)
        _trace_event(
            trace_id,
            stage="step",
            step="analyze",
            plugins=analysis_plugins,
            runtime_plugins=primary_plugins,
            skill_ids=runtime_plan.get("skill_ids") or [],
            ab_bucket=runtime_plan.get("ab_bucket", "A"),
        )

        out = None
        err = None
        # 1) 主链尝试
        try:
            state_for_subgraph = {**state, "analysis_plugins": primary_plugins}
            out = await analysis_subgraph.ainvoke(state_for_subgraph)
        except Exception as e:
            err = e
            _trace_event(
                trace_id,
                stage="step",
                step="analyze",
                result="error",
                failure_code=FailureCode.STEP_EXCEPTION.value,
                error=str(e)[:200],
                action="retry_with_fallback",
            )
            # 2) 同类 skill 回退链重试
            try:
                state_for_subgraph = {**state, "analysis_plugins": fallback_plugins}
                out = await analysis_subgraph.ainvoke(state_for_subgraph)
                _trace_event(
                    trace_id,
                    stage="fallback",
                    step="analyze",
                    action="fallback_applied",
                    failure_code=FailureCode.FALLBACK_APPLIED.value,
                    plugins=fallback_plugins,
                )
            except Exception as e2:
                err = e2

        duration_ana = round(time.perf_counter() - t0_ana, 4)
        if out is None:
            _trace_event(
                trace_id,
                stage="fallback",
                step="analyze",
                action="skip_with_explanation",
                failure_code=FailureCode.RETRY_EXHAUSTED.value,
                error=str(err)[:200] if err else "",
            )
            step_outputs = list(state.get("step_outputs") or [])
            step_outputs.append(
                {
                    "step": "analyze",
                    "reason": "",
                    "result": {
                        "skipped": "analyze_failed_after_retry",
                        "error": str(err)[:160] if err else "",
                        "failure_code": FailureCode.RETRY_EXHAUSTED.value,
                    },
                }
            )
            thinking_logs = _append_thinking(
                {**state, "thinking_logs": state.get("thinking_logs") or []},
                "analyze",
                "分析步骤失败，已自动跳过并继续后续步骤。",
            )
            return {
                **base,
                "trace_id": trace_id,
                "skill_ab_bucket": runtime_plan.get("ab_bucket", "A"),
                "failure_code": FailureCode.SKIPPED_WITH_EXPLANATION.value,
                "step_outputs": step_outputs,
                "thinking_logs": thinking_logs,
                "current_step": (base.get("current_step") or 0) + 1,
            }

        _trace_event(trace_id, stage="step", step="analyze", result="ok", duration=duration_ana)
        step_outputs = list(state.get("step_outputs") or [])
        step_outputs.append({"step": "analyze", "reason": "", "result": {"semantic_score": (out.get("analysis") or {}).get("semantic_score", 0), "angle": (out.get("analysis") or {}).get("angle", "")}})
        thinking_logs = _append_thinking({**state, "thinking_logs": state.get("thinking_logs") or []}, "analyze", f"分析完成，关联度 {(out.get('analysis') or {}).get('semantic_score', 0)}，切入点：{(out.get('analysis') or {}).get('angle', '')}")
        return {
            **out,
            "trace_id": trace_id,
            "skill_ab_bucket": runtime_plan.get("ab_bucket", "A"),
            "step_outputs": step_outputs,
            "thinking_logs": thinking_logs,
        }

    async def generate_node(state: MetaState) -> dict:
        base = _ensure_meta_state(state)
        trace_id = (base.get("trace_id") or "").strip() or _build_trace_id(base.get("session_id", ""))
        plan = base.get("plan") or []
        current = base.get("current_step") or 0
        params = (plan[current].get("params") or {}) if current < len(plan) else {}
        state_with_platform = {
            **state,
            "_generate_platform": params.get("platform", ""),
            "_generate_output_type": params.get("output_type", "text"),
        }
        out = None
        err = None
        try:
            out = await generation_subgraph.ainvoke(state_with_platform)
        except Exception as e:
            err = e
            _trace_event(
                trace_id,
                stage="step",
                step="generate",
                result="error",
                failure_code=FailureCode.STEP_EXCEPTION.value,
                error=str(e)[:200],
                action="retry_with_fallback",
            )
            # 生成兜底：强制 text_generator 再试一次
            try:
                fallback_state = {**state_with_platform, "generation_plugins": fallback_plugins_for_step("generate", base.get("generation_plugins") or [])}
                out = await generation_subgraph.ainvoke(fallback_state)
                _trace_event(
                    trace_id,
                    stage="fallback",
                    step="generate",
                    action="fallback_applied",
                    failure_code=FailureCode.FALLBACK_APPLIED.value,
                )
            except Exception as e2:
                err = e2

        if out is None:
            _trace_event(
                trace_id,
                stage="fallback",
                step="generate",
                action="skip_with_explanation",
                failure_code=FailureCode.RETRY_EXHAUSTED.value,
                error=str(err)[:200] if err else "",
            )
            step_outputs = list(state.get("step_outputs") or [])
            step_outputs.append(
                {
                    "step": "generate",
                    "reason": "",
                    "result": {
                        "skipped": "generate_failed_after_retry",
                        "error": str(err)[:160] if err else "",
                        "failure_code": FailureCode.RETRY_EXHAUSTED.value,
                    },
                }
            )
            thinking_logs = _append_thinking(
                {**state, "thinking_logs": state.get("thinking_logs") or []},
                "generate",
                "生成步骤失败，已自动跳过并继续后续步骤。",
            )
            return {
                **base,
                "trace_id": trace_id,
                "failure_code": FailureCode.SKIPPED_WITH_EXPLANATION.value,
                "step_outputs": step_outputs,
                "thinking_logs": thinking_logs,
                "current_step": (base.get("current_step") or 0) + 1,
            }

        step_outputs = list(state.get("step_outputs") or [])
        content = out.get("content", "")
        _trace_event(
            trace_id,
            stage="step",
            step="generate",
            result="ok",
            platform=params.get("platform", ""),
            output_type=params.get("output_type", "text"),
            content_len=len(content or ""),
        )
        step_outputs.append({"step": "generate", "reason": "", "result": {"content_length": len(content), "preview": content[:150]}})
        thinking_logs = _append_thinking({**state, "thinking_logs": state.get("thinking_logs") or []}, "generate", f"已生成内容，长度 {len(content)} 字符")
        return {**out, "trace_id": trace_id, "step_outputs": step_outputs, "thinking_logs": thinking_logs}

    async def evaluate_node(state: MetaState) -> dict:
        base = _ensure_meta_state(state)
        user_input_str = base.get("user_input") or ""
        user_data = _parse_user_payload(user_input_str)
        brand = user_data.get("brand_name", "")
        topic = user_data.get("topic", "")
        plan = base.get("plan") or []
        steps_used = "、".join((s.get("step") or "") for s in plan if s.get("step"))
        eval_context = {
            "brand_name": brand,
            "topic": topic,
            "analysis": base.get("analysis", {}),
            "steps_used": steps_used or "未提供",
        }
        evaluation = await ai_svc.evaluate_content(base.get("content", ""), eval_context)
        need_revision = evaluation.get("overall_score", 0) < 6
        step_outputs = list(base.get("step_outputs") or [])
        step_outputs.append({"step": "evaluate", "reason": "", "result": {"overall_score": evaluation.get("overall_score", 0), "suggestions": evaluation.get("suggestions", "")}})
        thinking_logs = _append_thinking({**base, "thinking_logs": base.get("thinking_logs") or []}, "evaluate", f"评估完成，综合分 {evaluation.get('overall_score', 0)}，{'需修订' if need_revision else '通过'}")
        return {
            **base,
            "evaluation": evaluation,
            "need_revision": need_revision,
            "step_outputs": step_outputs,
            "thinking_logs": thinking_logs,
            "current_step": (base.get("current_step") or 0) + 1,
        }

    async def skip_node(state: MetaState) -> dict:
        base = _ensure_meta_state(state)
        return {"current_step": (base.get("current_step") or 0) + 1}

    async def casual_reply_node(state: MetaState) -> dict:
        """闲聊回复：调用 reply_casual，直接返回对话内容，不执行检索/分析/生成。"""
        base = _ensure_meta_state(state)
        user_input_str = base.get("user_input") or ""
        user_data = _parse_user_payload(user_input_str)
        message = (user_data.get("raw_query") or "").strip()
        history_text = (user_data.get("conversation_context") or "").strip()
        if history_text:
            history_text = f"以下是近期对话：\n{history_text}\n\n"
        # 统一澄清入口：既支持“创作结果的模糊评价”，也支持“意图不清晰”的自然澄清
        plan = base.get("plan") or []
        step_params = {}
        if isinstance(plan, list) and plan:
            step0 = plan[0] if isinstance(plan[0], dict) else {}
            step_params = step0.get("params") or step0.get("parameters") or {}

        clarification_mode = (user_data.get("has_ambiguous_feedback_after_creation") is True) or bool(step_params.get("clarify"))
        clarification_kind = (step_params.get("clarification_kind") or "").strip() if isinstance(step_params, dict) else ""
        clarification_question = (step_params.get("question") or "").strip() if isinstance(step_params, dict) else ""
        suggested_next_desc = ""
        if clarification_mode:
            suggested_plan = user_data.get("session_suggested_next_plan") or []
            if isinstance(suggested_plan, list):
                suggested_next_desc = "、".join(
                    (s.get("step") or "") + ("：" + (s.get("reason") or ""))[:20]
                    for s in suggested_plan[:3] if isinstance(s, dict)
                ) or "生成内容"
        user_context = ""
        try:
            uid = base.get("user_id") or ""
            if uid:
                user_context = await memory_svc.get_user_summary(uid) or ""
        except Exception as e:
            logger.warning("casual_reply_node: 获取用户摘要失败: %s", e)
        logger.info(
            "casual_reply_node: message_len=%d, history_len=%d, user_summary_len=%d, clarification_mode=%s",
            len(message or ""),
            len(history_text or ""),
            len(user_context or ""),
            bool(clarification_mode),
        )
        reply = await ai_svc.reply_casual(
            message=message,
            history_text=history_text,
            clarification_mode=clarification_mode,
            clarification_kind=clarification_kind,
            clarification_question=clarification_question,
            suggested_next_desc=suggested_next_desc,
            user_context=user_context,
        )
        step_outputs = list(base.get("step_outputs") or [])
        reason = "已进行自然澄清/引导" if clarification_mode else "用户处于闲聊，直接回复"
        step_outputs.append({"step": "casual_reply", "reason": reason, "result": {"reply_length": len(reply or "")}})
        thinking_logs = _append_thinking(base, "闲聊回复", reason)
        return {
            **base,
            "content": reply or "",
            "step_outputs": step_outputs,
            "thinking_logs": thinking_logs,
            "current_step": len(plan),
        }

    def _eval_after_evaluate(state: MetaState) -> str:
        """评估后：需修订则进入人工决策节点（interrupt），否则回调度。"""
        return "human_decision" if state.get("need_revision") else "router"

    def _human_decision_next(state: MetaState) -> str:
        """人工决策后：按 next_node（由 human_decision 节点写入）路由。"""
        return "generate" if state.get("next_node") == "generate" else "router"

    def human_decision_node(state: MetaState) -> dict:
        """人工介入：暂停并等待「是否修订」决策，恢复后按决策路由。"""
        from langgraph.types import interrupt
        base = _ensure_meta_state(state)
        payload = {
            "message": "评估完成，是否修订？",
            "evaluation": base.get("evaluation", {}),
            "need_revision": base.get("need_revision", False),
        }
        decision = interrupt(payload)
        if decision in ("revise", True) or (isinstance(decision, dict) and decision.get("action") == "revise"):
            next_node = "generate"
        else:
            next_node = "router"
        return {**base, "next_node": next_node, "human_decision": decision}

    from langgraph.graph import END, StateGraph

    def _planning_shortcut_next(state: MetaState) -> str:
        """进入 planning 前短路：若已走 shortcut 则直接进 router，否则进 planning。"""
        return "router" if state.get("_from_planning_shortcut") else "planning"

    async def planning_shortcut_node(state: MetaState) -> dict:
        """进入 planning 前短路：极短闲聊、模糊评价直接组 1 步 casual_reply，跳过 LLM 规划（与旧版对齐）。"""
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        trace_id = (base.get("trace_id") or "").strip() or _build_trace_id(base.get("session_id", ""))
        user_input = base.get("user_input") or ""
        data = _parse_user_payload(user_input)
        raw_query = (data.get("raw_query") or "").strip()
        continue_words = {"需要", "继续", "然后呢", "再说说", "还有吗"}
        existing_plan = base.get("plan") or []
        current_step = int(base.get("current_step") or 0)
        has_remaining_plan = bool(existing_plan) and current_step < len(existing_plan)

        # “继续类短句”优先触发续跑：若会话已有未完成计划，直接续跑，不重复意图分类
        if raw_query in continue_words and has_remaining_plan:
            thought = f"检测到继续类短句「{raw_query}」，沿用当前计划从第 {current_step + 1} 步续跑"
            thinking_logs = _append_thinking(base, "策略脑规划", thought)
            _trace_event(
                trace_id,
                stage="fallback",
                action="continue_trigger",
                reason=raw_query,
                current_step=current_step,
            )
            return {
                **base,
                "trace_id": trace_id,
                "thinking_logs": thinking_logs,
                "_from_planning_shortcut": True,
            }

        # 承接上轮建议：用户回复“好的/开始/继续”等，自动执行上轮 suggested_next_plan
        accept_words = {"好的", "好", "行", "可以", "开始", "继续", "没问题", "可以的", "好呀", "走起"}
        suggested_plan = data.get("session_suggested_next_plan")
        if raw_query in accept_words and isinstance(suggested_plan, list) and suggested_plan:
            plan = [s for s in suggested_plan if isinstance(s, dict) and (s.get("step") or "").strip()]
            if plan:
                thought = f"用户确认继续（{raw_query}），采用上轮建议计划执行 {len(plan)} 步"
                thinking_logs = _append_thinking(base, "策略脑规划", thought)
                duration = round(time.perf_counter() - t0, 4)
                logger.info(
                    "intent_step: trace_id=%s shortcut accepted suggested plan (skip intent classify), raw=%r, steps=%d",
                    trace_id,
                    raw_query[:80],
                    len(plan),
                )
                return {
                    **base,
                    "trace_id": trace_id,
                    "plan": plan,
                    "task_type": "follow_up_execute",
                    "current_step": 0,
                    "thinking_logs": thinking_logs,
                    "step_outputs": [],
                    "planning_duration_sec": duration,
                    "_from_planning_shortcut": True,
                }

        # 极短闲聊：与 processor 一致，直接 casual_reply
        try:
            from core.intent.processor import SHORT_CASUAL_REPLIES
            if raw_query in SHORT_CASUAL_REPLIES and len(raw_query) <= 8:
                plan = [{"step": "casual_reply", "params": {}, "reason": "用户处于闲聊，直接回复"}]
                thought = "用户处于闲聊，规划一步 casual_reply"
                thinking_logs = _append_thinking(base, "策略脑规划", thought)
                duration = round(time.perf_counter() - t0, 4)
                logger.info("intent_step: trace_id=%s shortcut casual_chat (skip intent classify), raw=%r", trace_id, raw_query[:80])
                return {
                    **base,
                    "trace_id": trace_id,
                    "plan": plan,
                    "task_type": "casual_chat",
                    "current_step": 0,
                    "thinking_logs": thinking_logs,
                    "step_outputs": [],
                    "analysis_plugins": [],
                    "generation_plugins": [],
                    "planning_duration_sec": duration,
                    "_from_planning_shortcut": True,
                }
        except Exception:
            pass
        # 模糊评价：用户对创作结果说「还行吧」等，引导指出问题或确认满足
        if data.get("has_ambiguous_feedback_after_creation"):
            plan = [{"step": "casual_reply", "params": {}, "reason": "用户对生成内容评价为合格但可能不太满意，需引导指出问题或确认是否满足"}]
            thought = f"用户回复「{raw_query[:30]}」，为对当前生成内容的模糊评价，规划 casual_reply 引导"
            thinking_logs = _append_thinking(base, "策略脑规划", thought)
            duration = round(time.perf_counter() - t0, 4)
            logger.info("intent_step: trace_id=%s shortcut ambiguous_feedback (skip intent classify), raw=%r", trace_id, raw_query[:80])
            return {
                **base,
                "trace_id": trace_id,
                "plan": plan,
                "task_type": "casual_chat",
                "current_step": 0,
                "thinking_logs": thinking_logs,
                "step_outputs": [],
                "analysis_plugins": [],
                "generation_plugins": [],
                "planning_duration_sec": duration,
                "_from_planning_shortcut": True,
            }
        return {**base, "trace_id": trace_id}

    # ---------- IP 打造三态流程：intake / planned / executing，每轮单步执行 ----------
    from intake_guide import merge_context as intake_merge_context
    from plans import IP_INTAKE_OPTIONAL_KEYS, IP_INTAKE_REQUIRED_KEYS

    async def _ip_run_one_step(base_state: dict, step_config: dict, ip_context: dict, step_outputs: list) -> dict:
        """单步执行 runner：用 ip_context 构建上下文，执行当前 step，返回 step_output。"""
        step_name = (step_config.get("step") or "").lower()
        params = step_config.get("params") or {}
        reason = step_config.get("reason", "")
        user_id = (base_state.get("user_id") or "").strip()
        brand = ip_context.get("brand_name") or ""
        product = ip_context.get("product_desc") or ""
        topic = ip_context.get("topic") or ""
        platform = params.get("platform") or ip_context.get("platform") or ""
        tags = list(ip_context.get("tags") or []) if isinstance(ip_context.get("tags"), list) else []
        if step_name == "memory_query":
            memory = await memory_svc.get_memory_for_analyze(user_id=user_id, brand_name=brand, product_desc=product, topic=topic, tags_override=tags or None)
            mc = memory.get("preference_context", "")
            return {"step": step_name, "reason": reason, "result": {"has_memory": bool(mc), "memory_context": mc}}
        if step_name == "analyze":
            plugins = step_config.get("plugins") or []
            if isinstance(plugins, str):
                plugins = [plugins] if plugins.strip() else []
            request = ContentRequest(user_id=user_id, brand_name=brand, product_desc=product, topic=topic, tags=tags)
            analysis_result, _ = await ai_svc.analyze(request, preference_context=None, context_fingerprint={"tags": tags}, analysis_plugins=plugins or None)
            merged = dict(analysis_result) if isinstance(analysis_result, dict) else {}
            return {"step": step_name, "reason": reason, "result": {"angle": merged.get("angle", ""), "account_diagnosis": merged.get("account_diagnosis"), "content": merged.get("angle") or str(merged)[:500]}}
        if step_name == "generate":
            analysis_for_gen = {"brand_name": brand, "product_desc": product, "topic": f"{topic} {platform}".strip()}
            generated = await ai_svc.generate(analysis_for_gen, topic=topic or platform, raw_query=base_state.get("user_input", ""), generation_plugins=base_state.get("generation_plugins") or ["text_generator"])
            return {"step": step_name, "reason": reason, "result": {"content": generated, "content_length": len(generated)}}
        if step_name == "casual_reply":
            msg = params.get("message") or ""
            if not msg.strip():
                from langchain_core.messages import SystemMessage, HumanMessage
                reply_res = await llm.ainvoke([SystemMessage(content="你是友好助手，简短回复。"), HumanMessage(content=base_state.get("user_input", ""))])
                msg = (reply_res.content or "").strip() or "请告诉我更多信息。"
            return {"step": step_name, "reason": reason, "result": {"reply": msg}}
        if step_name == "web_search":
            query = params.get("query") or f"{brand} {product} {topic}".strip()
            results = await web_searcher.search(query, num_results=5)
            txt = web_searcher.format_results_as_context(results)
            return {"step": step_name, "reason": reason, "result": {"search_count": len(results), "summary": txt[:300]}}
        if step_name == "kb_retrieve":
            query = params.get("query") or f"{brand} {product} {topic}".strip() or "营销策略"
            passages = []
            if knowledge_port is not None:
                try:
                    passages = await knowledge_port.retrieve(query, top_k=4)
                except Exception as e:
                    logger.warning("kb_retrieve 失败: %s", e)
            return {"step": step_name, "reason": reason, "result": {"passage_count": len(passages), "summary": "\n\n".join(passages)[:500] if passages else ""}}
        if step_name == "evaluate":
            content = ""
            for o in reversed(step_outputs):
                r = o.get("result") if isinstance(o.get("result"), dict) else {}
                if r.get("content"):
                    content = r.get("content", "")
                    break
            if not content:
                return {"step": step_name, "reason": reason, "result": {"skipped": "no_content_to_evaluate"}}
            try:
                evaluation = await ai_svc.evaluate_content(content, {"topic": topic, "brand_name": brand})
                return {"step": step_name, "reason": reason, "result": {"overall_score": evaluation.get("overall_score", 0), "suggestions": evaluation.get("suggestions", "")}}
            except Exception as e:
                logger.warning("evaluate 失败: %s", e)
                return {"step": step_name, "reason": reason, "result": {"skipped": str(e)[:100]}}
        return {"step": step_name, "reason": reason, "result": {"skipped": "unknown_step"}}

    async def ip_build_router_node(state: MetaState) -> dict:
        """IP 打造三态路由：若 phase 为 intake/planned/executing 则处理并返回 ip_build_handled=True，否则交后续节点。"""
        base = _ensure_meta_state(state)
        phase = (base.get("phase") or "").strip()
        if phase not in (IP_BUILD_PHASE_INTAKE, IP_BUILD_PHASE_PLANNED, IP_BUILD_PHASE_EXECUTING):
            return {**base}
        user_input_str = base.get("user_input") or ""
        try:
            user_data = json.loads(user_input_str) if isinstance(user_input_str, str) else {}
        except (TypeError, json.JSONDecodeError):
            user_data = {}
        raw_query = (user_data.get("raw_query") or "").strip()
        if phase == IP_BUILD_PHASE_INTAKE:
            intent_agent = IntentAgent(llm)
            intent_result = await intent_agent.classify_intent(user_input=raw_query, conversation_context="")
            extracted = {k: (user_data.get(k) or "").strip() for k in IP_INTAKE_REQUIRED_KEYS + IP_INTAKE_OPTIONAL_KEYS if (user_data.get(k) or "").strip()}
            extracted["_raw_query"] = raw_query
            next_state = await ip_build_flow.intake_node(base, intent_result, extracted, llm)
            # 体验优化：当必填信息在本轮已补齐时，直接进入 planned→executing（固定模板 Plan）
            if (next_state.get("phase") == IP_BUILD_PHASE_PLANNED) and not (next_state.get("pending_questions") or []):
                try:
                    planning_agent = PlanningAgent(llm)
                    next_state = await ip_build_flow.plan_once_node(next_state, planning_agent, intent_result)
                except Exception as e:
                    logger.warning("IP planned→executing 直通失败，将在下一轮继续: %s", e)
            # 一致性：生成计划后尚未执行 step 时，保证有稳定的用户可见文案（含固定模板名称）
            if next_state.get("phase") == IP_BUILD_PHASE_EXECUTING and not (next_state.get("content") or "").strip():
                next_state["content"] = _ip_build_plan_ready_message(next_state.get("plan_template_id"), variant="intake")
            next_state["ip_build_handled"] = True
            return next_state
        if phase == IP_BUILD_PHASE_PLANNED:
            # 重规划或首次进入：planned 阶段不强依赖 LLM 意图识别（避免外部模型慢/卡住阻塞进入固定 Plan）
            # 规则：优先使用 raw_query（含“打造/诊断/内容”等关键词），否则沿用 state.intent，兜底 free_discussion
            intent_result = {
                "intent": (raw_query or base.get("intent") or "free_discussion"),
                "raw_query": raw_query,
                "confidence": 0.5,
                "reason": "planned 阶段规则意图推断（避免 LLM 阻塞）",
            }
            extracted = {k: (user_data.get(k) or "").strip() for k in IP_INTAKE_REQUIRED_KEYS + IP_INTAKE_OPTIONAL_KEYS if (user_data.get(k) or "").strip()}
            if extracted:
                base = {**base, "ip_context": intake_merge_context(base.get("ip_context") or {}, extracted, overwrite_keys=("topic",))}
            planning_agent = PlanningAgent(llm)
            next_state = await ip_build_flow.plan_once_node(base, planning_agent, intent_result)
            # 一致性：planned→executing 后尚未跑具体 step 时，给出进度提示（含固定模板名称）
            if next_state.get("phase") == IP_BUILD_PHASE_EXECUTING and not (next_state.get("content") or "").strip():
                next_state["content"] = _ip_build_plan_ready_message(next_state.get("plan_template_id"), variant="planned")
            next_state["ip_build_handled"] = True
            return next_state
        if phase == IP_BUILD_PHASE_EXECUTING:
            async def _runner(b: dict, sc: dict, ip_ctx: dict, outputs: list):
                return await _ip_run_one_step(b, sc, ip_ctx, outputs)
            next_state = await ip_build_flow.execute_one_step_node(base, _runner)
            # 一致性：中间 step 执行阶段通常不会产出 content（只有 phase=done 才汇总），因此需要兜底进度文案
            if (
                next_state.get("phase") == IP_BUILD_PHASE_EXECUTING
                and not (next_state.get("pending_questions") or [])
                and not (next_state.get("content") or "").strip()
            ):
                executed = len(next_state.get("step_outputs") or [])
                next_state["content"] = f"我已完成第 {executed} 步（或已推进到下一步）。若本步需要补全参数，我会先问你；你可以直接回复继续。"
            next_state["ip_build_handled"] = True
            return next_state
        return {**base}

    workflow = StateGraph(MetaState)
    workflow.add_node("ip_build_router", ip_build_router_node)
    workflow.add_node("planning_shortcut", planning_shortcut_node)
    workflow.add_node("planning", planning_node)

    def router_node(state: MetaState) -> dict:
        """调度节点：透传 state；编排层对齐旧版——改写请求注入 generate params、get_plugins_for_task 写回插件列表。"""
        out = dict(state)
        plan = list(out.get("plan") or [])
        user_input_str = out.get("user_input") or ""
        try:
            user_data = json.loads(user_input_str) if isinstance(user_input_str, str) else {}
        except (TypeError, json.JSONDecodeError):
            user_data = {}
        # 改写请求：为 generate 步注入 output_type=rewrite、platform
        if user_data.get("rewrite_previous_for_platform") and user_data.get("rewrite_platform"):
            rp = (user_data.get("rewrite_platform") or "").strip()
            if rp:
                for s in plan:
                    if (s.get("step") or "").lower() == "generate":
                        p = dict(s.get("params") or {})
                        p["output_type"] = "rewrite"
                        p["platform"] = rp
                        s["params"] = p
                out["plan"] = plan
                logger.info("router: 改写请求已为 generate 步注入 output_type=rewrite, platform=%s", rp)
        # 插件列表优先使用策略脑（Planning Agent）从 plan 中解析的结果，实现「按 plan 动态调用插件」。
        # 仅当 planning 未给出任何插件（如走 planning_shortcut 或 plan 未指定 plugins）时，才用 task_plugin_registry 兜底。
        has_plan_plugins = bool(out.get("analysis_plugins") or out.get("generation_plugins"))
        if not has_plan_plugins:
            task_type = (out.get("task_type") or "").strip()
            step_names = [(s.get("step") or "").lower() for s in plan if isinstance(s, dict)]
            try:
                from core.task_plugin_registry import get_plugins_for_task
                inferred_analysis, inferred_generation = get_plugins_for_task(task_type, step_names)
                out["analysis_plugins"] = inferred_analysis
                out["generation_plugins"] = inferred_generation
            except Exception as e:
                logger.debug("get_plugins_for_task 失败: %s", e)
        out.pop("_from_planning_shortcut", None)
        return out

    workflow.add_node("router", router_node)
    workflow.add_node("parallel_retrieval", parallel_retrieval_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("evaluate", evaluate_node)
    workflow.add_node("human_decision", human_decision_node)
    workflow.add_node("skip", skip_node)
    workflow.add_node("casual_reply", casual_reply_node)
    workflow.add_node("compilation", compilation_node)
    workflow.add_node("reasoning_loop", reasoning_loop_node)

    def _ip_build_router_next(state: MetaState) -> str:
        if state.get("ip_build_handled"):
            return "end"
        return "planning_shortcut"

    workflow.set_entry_point("ip_build_router")
    workflow.add_conditional_edges("ip_build_router", _ip_build_router_next, {"end": END, "planning_shortcut": "planning_shortcut"})
    workflow.add_conditional_edges("planning_shortcut", _planning_shortcut_next, {"router": "router", "planning": "planning"})
    workflow.add_edge("planning", "router")
    workflow.add_conditional_edges("router", _router_next, {"parallel_retrieval": "parallel_retrieval", "analyze": "analyze", "generate": "generate", "evaluate": "evaluate", "skip": "skip", "casual_reply": "casual_reply", "compilation": "compilation"})
    
    # 循环推理：在执行节点后添加 reasoning_loop 节点
    workflow.add_edge("parallel_retrieval", "reasoning_loop")
    workflow.add_edge("analyze", "reasoning_loop")
    workflow.add_edge("generate", "reasoning_loop")
    workflow.add_edge("skip", "reasoning_loop")
    workflow.add_edge("casual_reply", "compilation")  # 闲聊直接到compilation
    
    # reasoning_loop 的条件边：继续执行或结束
    def _reasoning_loop_next(state: dict) -> str:
        """判断是否继续循环或结束"""
        next_action = state.get("_next_action", "end")
        should_continue = state.get("_should_continue", False)
        reason = state.get("_reasoning_reason", "")
        logger.info(f"_reasoning_loop_next: next_action={next_action}, should_continue={should_continue}, reason={reason}")
        
        if should_continue and next_action == "continue":
            return "continue"
        else:
            return "end"
    
    workflow.add_conditional_edges("reasoning_loop", _reasoning_loop_next, {"continue": "router", "end": "compilation"})
    workflow.add_edge("compilation", END)
    
    workflow.add_conditional_edges("evaluate", _eval_after_evaluate, {"human_decision": "human_decision", "router": "router"})
    workflow.add_conditional_edges("human_decision", _human_decision_next, {"generate": "generate", "router": "router"})

    # 使用 Checkpointer 持久化 LangGraph 状态，支持跨会话记忆与上下文延续
    checkpointer = None
    try:
        import os
        db_url = os.getenv("DATABASE_URL", "")
        if db_url and "postgresql" in db_url:
            sync_url = db_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
                from langgraph.checkpoint.postgres import create_pool
                pool = create_pool(sync_url)
                checkpointer = PostgresSaver(pool)
                checkpointer.setup()
                logger.info("使用 Postgres Checkpointer 持久化 LangGraph 状态")
            except ImportError:
                pass
    except Exception as e:
        logger.debug(f"Postgres Checkpointer: {e}")

    if checkpointer is None:
        try:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
            logger.info("使用 MemorySaver（进程内持久化）")
        except Exception:
            pass

    return workflow.compile(checkpointer=checkpointer)

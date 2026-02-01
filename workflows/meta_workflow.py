"""
元工作流（深度思考）：策略脑构建思维链 → 编排层执行 → 汇总报告。
策略脑根据用户意图规划执行步骤（CoT），编排层动态调用分析脑、生成脑、搜索等模块。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

# 统一接口配置：config.api_config，引用 web_search 接口
from config.search_config import get_search_config
from core.plugin_registry import get_registry
from core.search import WebSearcher
from domain.memory import MemoryService
from models.request import ContentRequest
from services.ai_service import SimpleAIService
from workflows.types import MetaState

logger = logging.getLogger(__name__)


def _append_thinking(state: dict, step_name: str, thought: str) -> list[dict]:
    logs = list(state.get("thinking_logs") or [])
    logs.append({"step": step_name, "thought": thought, "timestamp": datetime.now(timezone.utc).isoformat()})
    return logs


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
        "current_step": state.get("current_step", 0),
        "thinking_logs": state.get("thinking_logs", []),
        "step_outputs": state.get("step_outputs", []),
        "search_context": state.get("search_context", ""),
        "memory_context": state.get("memory_context", ""),
    }


def build_meta_workflow(
    ai_service: SimpleAIService | None = None,
    web_searcher: WebSearcher | None = None,
    memory_service: MemoryService | None = None,
    metrics: dict | None = None,
    track_duration: Any = None,
) -> Any:
    """
    构建元工作流（深度思考）：
    1. planning_node（策略脑）：构建思维链
    2. orchestration_node（编排层）：按思维链调用模块
    3. compilation_node（汇总）：整合结果

    依赖注入：web_searcher、memory_service 可注入以便测试或替换实现。
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
        策略脑：根据用户意图构建思维链（Chain of Thought）。
        分析用户目标，规划需要哪些步骤（搜索、分析、生成、评估等）。
        """
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        user_input = base.get("user_input") or ""
        
        try:
            data = json.loads(user_input) if isinstance(user_input, str) else {}
        except (TypeError, json.JSONDecodeError):
            data = {}
        
        brand = (data.get("brand_name") or "").strip()
        product = (data.get("product_desc") or "").strip()
        topic = (data.get("topic") or "").strip()
        raw_query = (data.get("raw_query") or "").strip()
        intent = (data.get("intent") or "").strip()
        conversation_context = (data.get("conversation_context") or "").strip()
        explicit_content_request = data.get("explicit_content_request") is True

        system_prompt = """你是策略规划专家（类似 DeepSeek 深度思考）。根据用户的会话意图，规划从分析到执行的思维链（Chain of Thought），有效回答用户问题。

可用模块（可扩展：注册自定义插件后，步骤名与注册名一致即可被编排执行）：
- web_search: 网络检索（竞品、热点、行业动态、通用信息）
- memory_query: 查询用户历史偏好与品牌事实
- bilibili_hotspot: B站热点榜单（检索 B站热门内容，提炼结构与风格，供生成 B站文案时借鉴；用户要生成 B站/小破站内容时可加入）
- analyze: 分析（营销场景=品牌与热点关联；通用场景=分析如何回答问题、提取关键信息）
- generate: 生成内容（文案、脚本等，params 可含 platform、output_type；未来可扩展图片、视频）
- evaluate: 评估内容质量
- 自定义插件: 如 competitor_analysis 等，需先在 PluginRegistry 注册

规划原则：
1. **按意图规划**：根据用户真实意图决定步骤，不必总是全流程。思维链 = 分析对话意图+用户画像+历史+上下文 → 规划回答逻辑 → 输出回答。
2. **是否包含 generate（关键）**：仅当用户**明确要求生成具体内容**（如「生成文案」「写一篇」「帮我写小红书文案」）时，才规划 generate 步骤。若用户只是陈述推广意向、目标人群（如「推广华为手机，年龄18-35」），**严禁**规划 generate，应输出策略/方案/分析/思路，类似顾问给出建议，供用户参考后决定下一步。
3. 营销意图但未明确要求生成：web_search + memory_query + analyze → 输出推广策略、渠道建议、内容方向（不生成成品文案）。
4. 营销意图且明确要求生成：可走 web_search + memory_query + analyze + generate + evaluate。
5. 当用户明确指定 B站/小破站/bilibili 平台生成文案时，在 analyze 之前加入 bilibili_hotspot 步骤。
6. 若用户要策略建议、竞品分析等，可只做 web_search + analyze，输出即建议。
7. 信息不足时先搜索；有用户历史时查询记忆。
8. 步骤数 2-6 个为宜。

输出格式：只输出一个 JSON 数组，每步包含：
- step: 模块名（web_search|memory_query|bilibili_hotspot|analyze|generate|evaluate）
- params: 参数（如 {"query": "..."}）
- reason: 为什么需要这步（1句话）

示例（生成 B站文案时加入 bilibili_hotspot）：
```json
[
  {"step": "bilibili_hotspot", "params": {}, "reason": "获取 B站热点结构与风格供借鉴"},
  {"step": "memory_query", "params": {}, "reason": "查询用户偏好"},
  {"step": "analyze", "params": {}, "reason": "分析品牌与热点关联"},
  {"step": "generate", "params": {"platform": "B站"}, "reason": "生成推广文案"},
  {"step": "evaluate", "params": {}, "reason": "评估内容质量"}
]
```

只输出 JSON 数组，不要其他文字。"""
        
        ctx_section = ""
        if conversation_context and (not brand or not product):
            ctx_section = f"\n【近期对话（主推广对象须从此提取）】\n{conversation_context[:800]}\n"
        elif conversation_context:
            ctx_section = f"\n【近期对话】\n{conversation_context[:600]}\n"
        
        explicit_hint = "用户已明确要求生成内容，可规划 generate 步骤。" if explicit_content_request else "**用户未明确要求生成内容，严禁规划 generate 步骤，输出应为策略/方案/分析/思路。**"
        user_prompt = f"""【用户目标（主推广对象，后续步骤须围绕此展开）】
品牌：{brand or "未指定"}
产品：{product or "未指定"}
话题/目标：{topic or raw_query or "推广"}
意图：{intent or "未指定"}
是否明确要求生成：{"是" if explicit_content_request else "否"}{ctx_section}
{explicit_hint}
注意：若用户提供了文档或链接作为「参考」，主推广对象仍是上述品牌/产品（或从近期对话中提取）。web_search 的 query 应围绕主推广对象。

请规划执行步骤（思维链）。"""
        
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        
        try:
            response = await llm.invoke(messages, task_type="planning", complexity="high")
            raw = response.strip()
            for prefix in ("```json", "```"):
                if raw.startswith(prefix):
                    raw = raw[len(prefix):].strip()
            if raw.endswith("```"):
                raw = raw[:raw.rfind("```")].strip()
            
            plan = json.loads(raw)
            if not isinstance(plan, list):
                plan = []
            # 安全过滤：用户未明确要求生成时，移除 generate 步骤
            if not explicit_content_request:
                plan = [s for s in plan if (s.get("step") or "").lower() != "generate"]
                if plan:
                    logger.info("策略脑: explicit_content_request=false，已移除 generate 步骤")
        except Exception as e:
            logger.warning("策略脑规划失败，使用默认流程: %s", e, exc_info=True)
            if explicit_content_request:
                plan = [
                    {"step": "analyze", "params": {}, "reason": "分析品牌与热点"},
                    {"step": "generate", "params": {}, "reason": "生成推广文案"},
                    {"step": "evaluate", "params": {}, "reason": "评估内容质量"},
                ]
            else:
                plan = [
                    {"step": "web_search", "params": {"query": f"{brand or product or topic or '推广'} 用户偏好 市场趋势"}, "reason": "了解市场与用户"},
                    {"step": "analyze", "params": {}, "reason": "分析并输出推广策略"},
                ]
        
        if not plan:
            if explicit_content_request:
                plan = [{"step": "analyze", "params": {}, "reason": "分析"}, {"step": "generate", "params": {}, "reason": "生成"}]
            else:
                plan = [{"step": "analyze", "params": {}, "reason": "分析并输出策略"}]
        
        thought = f"策略脑已规划 {len(plan)} 个步骤：" + " → ".join(s.get("step", "") for s in plan)
        thinking_logs = _append_thinking(base, "策略脑规划", thought)
        duration = round(time.perf_counter() - t0, 4)
        
        return {
            **base,
            "plan": plan,
            "current_step": 0,
            "thinking_logs": thinking_logs,
            "step_outputs": [],
            "planning_duration_sec": duration,
        }

    async def orchestration_node(state: MetaState) -> dict:
        """
        编排层：按思维链顺序执行各模块。
        支持：web_search、memory_query、analyze、generate、evaluate。
        """
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        plan = base.get("plan") or []
        user_input_str = base.get("user_input") or ""
        user_id = base.get("user_id") or ""
        session_id = base.get("session_id") or ""
        
        try:
            user_data = json.loads(user_input_str) if isinstance(user_input_str, str) else {}
        except (TypeError, json.JSONDecodeError):
            user_data = {}
        
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
            "analysis": {},
            "content": "",
            "evaluation": {},
        }
        
        step_outputs = []
        thinking_logs = list(base.get("thinking_logs") or [])

        # 可并行步骤：web_search、memory_query、bilibili_hotspot（无依赖）
        PARALLEL_STEPS = {"web_search", "memory_query", "bilibili_hotspot"}
        parallel_plans = [s for s in plan if (s.get("step") or "").lower() in PARALLEL_STEPS]
        sequential_plans = [s for s in plan if (s.get("step") or "").lower() not in PARALLEL_STEPS]

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

        def _step_runner(sc: dict):
            name = (sc.get("step") or "").lower()
            if name == "web_search":
                return _run_web_search(sc)
            if name == "memory_query":
                return _run_memory_query(sc)
            if name == "bilibili_hotspot":
                return _run_bilibili_hotspot(sc)
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
                if search_parts:
                    context["search_results"] = "\n\n".join(search_parts)

        # 顺序执行其余步骤
        for i, step_config in enumerate(sequential_plans):
            step_name = step_config.get("step", "")
            params = step_config.get("params") or {}
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
                    # 分析时可引用搜索结果和记忆
                    preference_ctx = context.get("memory_context") or None
                    if context.get("search_results"):
                        if preference_ctx:
                            preference_ctx += f"\n\n【网络检索信息】\n{context['search_results']}"
                        else:
                            preference_ctx = f"【网络检索信息】\n{context['search_results']}"
                    # 计划中无 generate 时，输出策略方案而非单点切入点
                    plan_has_generate = any((s.get("step") or "").lower() == "generate" for s in plan)
                    strategy_mode = not plan_has_generate
                    analysis_result, cache_hit = await ai_svc.analyze(
                        request,
                        preference_context=preference_ctx,
                        context_fingerprint={"tags": context.get("effective_tags", [])},
                        strategy_mode=strategy_mode,
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
                    thought = "分析完成，已输出推广策略" if strategy_mode else f"分析完成，关联度 {analysis_result.get('semantic_score', 0)}，切入点：{analysis_result.get('angle', '')}"
                    thinking_logs = _append_thinking(
                        {**base, "thinking_logs": thinking_logs},
                        step_name,
                        thought,
                    )
                
                elif step_name == "generate":
                    platform = params.get("platform", "")
                    output_type = params.get("output_type", "text")
                    if platform:
                        topic_with_platform = f"{topic} {platform}".strip()
                    else:
                        topic_with_platform = topic
                    
                    generated = await ai_svc.generate(
                        context.get("analysis", {}),
                        topic=topic_with_platform,
                        raw_query=raw_query,
                        session_document_context=doc_context,
                        output_type=output_type,
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
                    eval_context = {
                        "brand_name": brand,
                        "topic": topic,
                        "analysis": context.get("analysis", {}),
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
                        f"评估完成，综合分 {evaluation.get('overall', 0)}，{'需修订' if context['need_revision'] else '通过'}",
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
        """汇总：整合思考过程与各步输出，生成 DeepSeek 风格的叙述式思维链与最终报告。"""
        from workflows.thinking_narrative import generate_thinking_narrative
        
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        step_outputs = base.get("step_outputs") or []
        thinking_logs = base.get("thinking_logs") or []
        user_input_str = base.get("user_input") or ""
        search_context = base.get("search_context") or ""
        analysis = base.get("analysis") or {}
        
        # 生成 DeepSeek 风格的连贯叙述（P1: 传入 used_tags 以便体现「根据您的偏好」）
        used_tags = base.get("used_tags") or []
        thinking_narrative = ""
        try:
            thinking_narrative = await generate_thinking_narrative(
                user_input_str=user_input_str,
                thinking_logs=thinking_logs,
                step_outputs=step_outputs,
                search_context=search_context,
                analysis=analysis,
                llm_client=llm,
                effective_tags=used_tags,
            )
        except Exception as e:
            logger.warning("思考叙述生成失败，使用步骤列表: %s", e)
            for entry in thinking_logs:
                thinking_narrative += f"- **{entry.get('step', '')}**: {entry.get('thought', '')}\n"
        
        report_lines = ["# 深度思考报告\n"]
        report_lines.append("## 思维链执行过程\n")
        report_lines.append(thinking_narrative.strip() or "（无）")
        report_lines.append("\n\n## 最终输出\n")
        final_content = base.get("content", "")
        if final_content:
            report_lines.append(final_content)
        else:
            # 无生成步骤时（如仅做策略分析、竞品分析），以分析结果作为输出
            analysis_obj = base.get("analysis") or {}
            if isinstance(analysis_obj, dict) and analysis_obj:
                angle = analysis_obj.get("angle", "")
                reason = analysis_obj.get("reason", "")
                if angle or reason:
                    report_lines.append((angle or "") + "\n\n" + (reason or ""))
            elif isinstance(analysis_obj, str) and analysis_obj.strip():
                report_lines.append(analysis_obj.strip())
        
        evaluation = base.get("evaluation", {})
        if evaluation and not evaluation.get("evaluation_failed"):
            report_lines.append(f"\n\n## 质量评估\n")
            report_lines.append(f"- 综合分：{evaluation.get('overall', 0)}/10\n")
            report_lines.append(f"- 改进建议：{evaluation.get('suggestions', '')}\n")
        
        compiled = "\n".join(report_lines).strip()
        thought = f"已整合 {len(step_outputs)} 个步骤的结果，生成最终报告"
        thinking_logs_final = _append_thinking(base, "汇总", thought)
        duration = round(time.perf_counter() - t0, 4)
        
        return {
            **base,
            "content": compiled,
            "thinking_logs": thinking_logs_final,
            "compilation_duration_sec": duration,
        }
    
    from langgraph.graph import StateGraph
    workflow = StateGraph(MetaState)
    
    if use_metrics:
        m_plan = metrics.get("planning")
        m_orch = metrics.get("orchestration")
        m_comp = metrics.get("compilation")
        
        async def wrapped_planning(state: MetaState) -> dict:
            return await track_duration(m_plan, planning_node, state)
        
        async def wrapped_orchestration(state: MetaState) -> dict:
            return await track_duration(m_orch, orchestration_node, state)
        
        async def wrapped_compilation(state: MetaState) -> dict:
            return await track_duration(m_comp, compilation_node, state)
        
        workflow.add_node("planning", wrapped_planning)
        workflow.add_node("orchestration", wrapped_orchestration)
        workflow.add_node("compilation", wrapped_compilation)
    else:
        workflow.add_node("planning", planning_node)
        workflow.add_node("orchestration", orchestration_node)
        workflow.add_node("compilation", compilation_node)
    
    workflow.set_entry_point("planning")
    workflow.add_edge("planning", "orchestration")
    workflow.add_edge("orchestration", "compilation")
    workflow.add_edge("compilation", END)
    
    return workflow.compile()

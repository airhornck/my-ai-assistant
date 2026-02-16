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
from workflows.analysis_brain_subgraph import build_analysis_brain_subgraph
from workflows.generation_brain_subgraph import build_generation_brain_subgraph
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
        策略脑：以专家原则根据用户意图构建思维链（Chain of Thought）。
        判断需要哪些能力（检索、分析、生成、评估等）来指导回答，充分利用现有能力；若发现缺少用户约束，在 reason 中注明需用户补充。
        用户采纳上轮「后续建议」时也走专家原则：将建议的下一步作为输入，由策略脑判断是直接执行、需用户补充、或先增加检索/分析等步骤。
        """
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        user_input = base.get("user_input") or ""
        
        try:
            data = json.loads(user_input) if isinstance(user_input, str) else {}
        except (TypeError, json.JSONDecodeError):
            data = {}
        
        # 性能优化：极短闲聊（如「还好」「嗯」）直接规划 casual_reply，跳过规划 LLM
        raw_query = (data.get("raw_query") or "").strip()
        try:
            from core.intent.processor import SHORT_CASUAL_REPLIES
            if raw_query in SHORT_CASUAL_REPLIES and len(raw_query) <= 8:
                plan = [{"step": "casual_reply", "params": {}, "reason": "用户处于闲聊，直接回复"}]
                thought = "用户处于闲聊，规划一步 casual_reply"
                thinking_logs = _append_thinking(base, "策略脑规划", thought)
                duration = round(time.perf_counter() - t0, 4)
                logger.info("planning_node 完成(闲聊快路径), duration=%.2fs, 跳过规划 LLM", duration)
                return {
                    **base,
                    "plan": plan,
                    "task_type": "casual_chat",
                    "current_step": 0,
                    "thinking_logs": thinking_logs,
                    "step_outputs": [],
                    "analysis_plugins": [],
                    "generation_plugins": [],
                    "planning_duration_sec": duration,
                }
        except Exception:
            pass

        # 模糊评价快路径：用户对创作结果说「还不错」「还好吧」等，表示合格但不很满意，需引导指出问题或确认足够
        if data.get("has_ambiguous_feedback_after_creation"):
            raw = (data.get("raw_query") or "").strip()
            plan = [{"step": "casual_reply", "params": {}, "reason": "用户对生成内容评价为合格但不很满意，需引导指出问题或确认是否足够"}]
            thought = f"用户回答「{raw}」，是对当前生成内容的模糊评价，表示合格但可能不太满意。需引导用户指出哪里有问题，或确认是否已经足够。规划 casual_reply 生成澄清性回复。"
            thinking_logs = _append_thinking(base, "策略脑规划", thought)
            duration = round(time.perf_counter() - t0, 4)
            logger.info("planning_node 完成(模糊评价快路径), duration=%.2fs, 跳过规划 LLM", duration)
            return {
                **base,
                "plan": plan,
                "task_type": "casual_chat",
                "current_step": 0,
                "thinking_logs": thinking_logs,
                "step_outputs": [],
                "analysis_plugins": [],
                "generation_plugins": [],
                "planning_duration_sec": duration,
            }

        # 采纳建议不在此短路：统一走专家原则，由策略脑判断直接执行 / 需用户补充 / 增加步骤
        brand = (data.get("brand_name") or "").strip()
        product = (data.get("product_desc") or "").strip()
        topic = (data.get("topic") or "").strip()
        if not raw_query:
            raw_query = (data.get("raw_query") or "").strip()
        intent = (data.get("intent") or "").strip()
        conversation_context = (data.get("conversation_context") or "").strip()
        explicit_content_request = data.get("explicit_content_request") is True
        # 采纳的后续建议若包含 generate，本轮视为「要求生成内容」，避免因 raw_query 仅为「需要」而被判为严禁 generate
        suggested_plan = data.get("session_suggested_next_plan") or []
        if data.get("user_accepted_suggestion") and isinstance(suggested_plan, list):
            if any((s.get("step") or "").lower() == "generate" for s in suggested_plan if isinstance(s, dict)):
                explicit_content_request = True

        system_prompt = """你是策略规划专家。**始终以专家原则进行规划**：根据用户意图判断需要哪些能力（检索、分析、生成等）来指导回答，充分利用现有能力；帮助客户厘清目标与缺失维度，必要时引导补充，若客户不补充则基于已有信息给出建议并生成，再通过后续建议与反馈迭代直至满意。不强行只规划一步生成，也不在信息不足时强行生成。

可用模块（可扩展：注册自定义插件后，步骤名与注册名一致即可被编排执行）：
- web_search: 网络检索（竞品、热点、行业动态、通用信息）
- memory_query: 查询用户历史偏好与品牌事实
- kb_retrieve: 知识库检索（行业方法论、案例等，供分析/生成时更垂直、更专业；需要专业方案时可加入）
- bilibili_hotspot: B站热点榜单（检索 B站热门内容，提炼结构与风格，供生成 B站文案时借鉴；用户要生成 B站/小破站内容时可加入）
- analyze: 分析（营销场景=品牌与热点关联；通用场景=分析如何回答问题、提取关键信息）
- generate: 生成内容（文案、脚本等，params 可含 platform、output_type；未来可扩展图片、视频）
- evaluate: 评估内容质量
- casual_reply: 闲聊回复（当用户处于问候、寒暄、无明确推广/生成需求时，仅此一步，不规划检索/分析/生成）
- 自定义插件: 如 competitor_analysis 等，需先在 PluginRegistry 注册

专家原则（日常规划与改写等场景均适用）：
1. **按意图选能力**：根据用户真实意图决定需要哪些能力、多少步骤，不必总是全流程。思维链 = 分析对话意图+用户画像+历史+上下文 → 判断需要哪些能力 → 规划步骤顺序 → 输出回答。
2. **是否包含 generate（关键）**：仅当用户**明确要求生成具体内容**（如「生成文案」「写一篇」「帮我写小红书文案」）时，才规划 generate 步骤。若用户只是陈述推广意向、目标人群（如「推广华为手机，年龄18-35」），**严禁**规划 generate，应输出策略/方案/分析/思路，类似顾问给出建议，供用户参考后决定下一步。
3. 营销意图但未明确要求生成：web_search + memory_query + analyze → 输出推广策略、渠道建议、内容方向（不生成成品文案）。
4. 营销意图且明确要求生成：按专家经验选能力，如 web_search + memory_query + analyze + generate + evaluate；若涉及 B站/小红书等平台，加入对应检索（如 bilibili_hotspot）以获取当前热点与风格后再生成。
5. 当用户明确指定 B站/小破站/bilibili 平台生成文案时，在 analyze 之前加入 bilibili_hotspot 步骤，用当前热点与风格指导生成。
6. 若用户要策略建议、竞品分析等，可只做 web_search + analyze，输出即建议。
7. 需要更垂直、专业的分析或方案时，可在 analyze 前加入 kb_retrieve 步骤（知识库检索）。
8. 信息不足时先搜索；有用户历史时查询记忆；步骤数 2-6 个为宜。
9. **改写请求**：当用户要求将「上文的已有内容」改写成某平台风格时，仍按专家原则选能力——先规划检索/分析（如 B站 用 bilibili_hotspot 获取当前热点与风格），再规划 generate 且 params 含 **output_type: "rewrite"**、**platform: "目标平台"**；严禁只规划一步 generate。
10. **采纳后续建议（继续创作）**：当用户采纳了上轮的「后续建议」时，表示**继续创作**意图。你会收到「建议的下一步」列表。若建议仅为 generate 且上文已有分析/内容，应**直接规划 generate（可加 evaluate）**，无需 web_search / memory_query / analyze，以体现继续创作意图；若建议含多步则按建议与专家判断执行。若当前缺少约束，在某步 reason 中注明需用户补充；若需结合当前热点再生成，可先加检索/分析再 generate。
11. **帮助客户实现目标（缺维度时的专家行为）**：当客户意图明确（如「生成文案」）但未补充关键维度时，你作为专家应仔细思考需要哪些维度才能达成目标。常见维度包括（可按任务类型增减）：**平台**（B站/小红书/抖音等）、**样式/体裁**（短视频脚本、图文、长文、口播稿等）、**长度**（字数或时长）、**目标人群**（年龄、兴趣、消费场景等）、**达成目标**（曝光/转化/种草/品牌认知等）、**调性/语气**（正式/轻松/幽默/专业等）、**卖点或核心信息**（要突出的产品卖点或品牌信息）、**禁忌/合规**（不能提的、敏感词）、**时效/节点**（节日、大促、热点等）。结合上下文与已有信息（品牌、产品、话题等）标出**已有维度**，在相应步骤的 reason 中**明确列出需客户补充的剩余维度**（如「需补充：平台、目标人群、期望长度」），引导客户只补缺失项；若客户表示不想补充（如「不用了」「直接生成吧」），则基于已有信息给出合理假设与建议，规划 analyze + generate，生成后再通过「后续建议」与评估/修订收集反馈，直至客户满意。
12. **闲聊**：仅当用户当前输入**纯粹为闲聊**（问候、寒暄、无任何推广/生成/分析需求，如「你好」「还好」「在吗」）时，steps 仅为 [{"step": "casual_reply", "reason": "用户处于闲聊，直接回复"}]。
13. **混合意图**：若用户输入包含问候但同时也提出了具体需求（如「你好，帮我诊断账号」、「你好，帮我写个文案」），**严禁**视为闲聊，必须根据需求规划相应步骤（如 web_search/analyze 等），忽略问候语部分。
14. **模糊评价后澄清**：当用户对上一轮创作结果给出模糊评价（如「还不错」「还行」「还好吧」）且会话存在「后续建议」时，表示用户对生成内容评价为**合格但可能不太满意**，未明确采纳建议。应规划 steps 仅为 [{"step": "casual_reply", "reason": "用户对内容评价合格但不满意，需引导指出问题或确认足够"}]。casual_reply 应生成 1-2 句引导性回复，帮助用户：(1) 指出哪些地方需要调整，或 (2) 确认当前内容是否已经足够。示例：「您觉得哪些地方需要调整？还是说这样就可以了？」**严禁**规划 web_search/analyze/generate/evaluate。

先判断任务类型 task_type（必填，三选一）：
- campaign_or_copy：用户要做活动策划、营销方案、文案生成、推广计划、内容日历等；
- ip_diagnosis：用户要诊断账号/IP 问题、看账号有什么问题；
- ip_building_plan：用户要从零做 IP 或要完整 IP 打造方案。

输出格式：只输出一个 JSON 对象，包含 task_type 与 steps（步骤数组）：
- task_type: 上述三选一
- steps: 数组，每步包含 step、params、reason

示例（活动策划+生成 B站文案）：
```json
{"task_type": "campaign_or_copy", "steps": [
  {"step": "bilibili_hotspot", "params": {}, "reason": "获取 B站热点结构与风格供借鉴"},
  {"step": "memory_query", "params": {}, "reason": "查询用户偏好"},
  {"step": "kb_retrieve", "params": {}, "reason": "检索知识库与案例"},
  {"step": "analyze", "params": {}, "reason": "分析品牌与热点关联"},
  {"step": "generate", "params": {"platform": "B站"}, "reason": "生成推广文案"},
  {"step": "evaluate", "params": {}, "reason": "评估内容质量"}
]}
```

示例（对上文内容改写成 B站风格，须先检索/分析再改写）：
```json
{"task_type": "campaign_or_copy", "steps": [
  {"step": "bilibili_hotspot", "params": {}, "reason": "获取 B站当前热点与风格供改写借鉴"},
  {"step": "analyze", "params": {}, "reason": "结合热点与上文内容提炼改写方向"},
  {"step": "generate", "params": {"platform": "B站", "output_type": "rewrite"}, "reason": "将上文内容改写成 B站风格"},
  {"step": "evaluate", "params": {}, "reason": "评估改写稿质量"}
]}
```

只输出 JSON 对象，不要其他文字。"""
        
        ctx_section = ""
        if conversation_context and (not brand or not product):
            ctx_section = f"\n【近期对话（主推广对象须从此提取）】\n{conversation_context[:800]}\n"
        elif conversation_context:
            ctx_section = f"\n【近期对话】\n{conversation_context[:600]}\n"
        
        accept_suggestion_section = ""
        if data.get("user_accepted_suggestion") and data.get("session_suggested_next_plan"):
            suggested = data.get("session_suggested_next_plan")
            if isinstance(suggested, list) and len(suggested) > 0:
                steps_desc = " → ".join(
                    (s.get("step") or "") + ("(" + (s.get("reason") or "") + ")" if s.get("reason") else "")
                    for s in suggested[:8]
                )
                step_names_only = [(s.get("step") or "").lower() for s in suggested if isinstance(s, dict)]
                only_generate = step_names_only == ["generate"]
                direct_hint = ""
                if only_generate:
                    direct_hint = "建议仅为「生成」且上文已有分析，请**直接规划 generate（可加 evaluate）**，无需 web_search / memory_query / analyze，以体现继续创作意图。"
                accept_suggestion_section = f"""
【用户本轮意图为「采纳上轮后续建议」= 继续创作】表示承接上文、执行上轮建议。建议的下一步为：{steps_desc}。
{direct_hint}
请以专家原则判断：若信息已足则直接按建议执行（steps 可与之一致）；若当前信息不足需在某步 reason 中注明需用户补充、或需结合当前热点再生成，可先加检索/分析再执行。本轮意图是采纳建议，不要将用户本句字面内容当作话题或搜索关键词，以上文会话的主推广对象与意图为准。
"""
        rewrite_section = ""
        if data.get("rewrite_previous_for_platform") and data.get("session_previous_content"):
            rp = (data.get("rewrite_platform") or "B站").strip()
            rewrite_section = f"""
【本次为改写请求】用户要求将上文的已有内容改写成「{rp}」风格（非重新做活动方案）。请按专家经验规划：先规划检索/分析等能力（如 B站 用 bilibili_hotspot 获取当前热点与风格，再 analyze 提炼改写方向），最后规划 generate 且 params 必须含 "output_type": "rewrite"、"platform": "{rp}"，以生成最符合当前热点趋势的改写稿。严禁只规划一步 generate。
"""
        ambiguous_feedback_section = ""
        if data.get("has_ambiguous_feedback_after_creation"):
            suggested = data.get("session_suggested_next_plan") or []
            steps_desc = "、".join((s.get("step") or "") for s in suggested[:5] if isinstance(s, dict))
            ambiguous_feedback_section = f"""
【用户对生成内容给出模糊评价，合格但可能不太满意】用户说「{raw_query}」，是对上一轮创作结果的评价（如「还不错」「还行」「还好吧」），表示合格但可能不太满意，**不是**明确采纳建议。请规划 steps 仅为 [{{"step": "casual_reply", "reason": "引导用户指出问题或确认是否足够"}}]。casual_reply 应生成 1-2 句引导性回复，帮助用户：(1) 指出哪些地方需要调整，或 (2) 确认当前内容是否已经足够。示例：「您觉得哪些地方需要调整？还是说这样就可以了？」**严禁**规划 web_search/analyze/generate/evaluate。
"""
        explicit_hint = "用户已明确要求生成内容，可规划 generate 步骤。" if explicit_content_request else "**用户未明确要求生成内容，严禁规划 generate 步骤，输出应为策略/方案/分析/思路。**"
        user_prompt = f"""【用户目标（主推广对象，后续步骤须围绕此展开）】
品牌：{brand or "未指定"}
产品：{product or "未指定"}
话题/目标：{topic or raw_query or "推广"}
意图：{intent or "未指定"}
是否明确要求生成：{"是" if explicit_content_request else "否"}{ctx_section}
{accept_suggestion_section}
{rewrite_section}
{ambiguous_feedback_section}
{explicit_hint}
注意：若用户提供了文档或链接作为「参考」，主推广对象仍是上述品牌/产品（或从近期对话中提取）。web_search 的 query 应围绕主推广对象。若用户意图是生成内容但缺少关键维度（平台、样式、长度、目标人群、达成目标、调性、卖点、禁忌、时效节点等），请结合上下文标出已有维度，在某步 reason 中**明确列出需用户补充的剩余维度**；若用户后续表示不补充，则基于已有信息给出建议并规划 generate，生成后通过后续建议与反馈迭代直至满意。

请以专家原则规划执行步骤：先判断需要哪些能力，再规划思维链。"""
        
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        
        task_type = ""
        plan = []
        try:
            response = await llm.invoke(messages, task_type="planning", complexity="high")
            raw = response.strip()
            for prefix in ("```json", "```"):
                if raw.startswith(prefix):
                    raw = raw[len(prefix):].strip()
            if raw.endswith("```"):
                raw = raw[:raw.rfind("```")].strip()
            
            parsed = json.loads(raw)
            # 新格式：{"task_type": "...", "steps": [...]}
            if isinstance(parsed, dict):
                task_type = (parsed.get("task_type") or "").strip() or ""
                steps = parsed.get("steps") or parsed.get("plan") or []
                plan = steps if isinstance(steps, list) else []
                # 允许从 JSON 显式指定插件（未来扩展）
                analysis_plugins = parsed.get("analysis_plugins") or []
                if isinstance(analysis_plugins, str):
                    analysis_plugins = [analysis_plugins]
            else:
                plan = parsed if isinstance(parsed, list) else []
                task_type = ""
                analysis_plugins = []
                # 兼容旧格式（仅数组）：根据步骤推断 task_type
                step_names = [(s.get("step") or "").lower() for s in plan] if plan else []
                if "kb_retrieve" in step_names and ("analyze" in step_names or "generate" in step_names):
                    task_type = "campaign_or_copy"
            if not isinstance(plan, list):
                plan = []
            # 安全过滤：用户未明确要求生成时，移除 generate 步骤
            if not explicit_content_request:
                plan = [s for s in plan if (s.get("step") or "").lower() != "generate"]
                if plan:
                    logger.info("策略脑: explicit_content_request=false，已移除 generate 步骤")
        except Exception as e:
            logger.warning("策略脑规划失败，使用默认流程: %s", e, exc_info=True)
            analysis_plugins = []
            if explicit_content_request:
                plan = [
                    {"step": "analyze", "params": {}, "reason": "分析品牌与热点"},
                    {"step": "generate", "params": {}, "reason": "生成推广文案"},
                    {"step": "evaluate", "params": {}, "reason": "评估内容质量"},
                ]
                task_type = "campaign_or_copy"
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
        
        # 改写请求：确保 plan 中的 generate 步骤带有 output_type=rewrite、platform，以便下游做风格改写
        if data.get("rewrite_previous_for_platform") and data.get("rewrite_platform"):
            rp = (data.get("rewrite_platform") or "B站").strip()
            for s in plan:
                if (s.get("step") or "").lower() == "generate":
                    p = s.get("params") or {}
                    if not isinstance(p, dict):
                        p = {}
                    p["output_type"] = "rewrite"
                    p["platform"] = rp
                    s["params"] = p
            logger.info("planning_node: 改写请求已为 generate 步骤注入 output_type=rewrite, platform=%s", rp)
        
        # 由任务类型与步骤从注册表推导插件列表（只登记拼装后或无需拼装的插件；后续新增任务仅需加注册表项）
        step_names = [(s.get("step") or "").lower() for s in plan]
        from core.task_plugin_registry import get_plugins_for_task
        inferred_analysis_plugins, generation_plugins = get_plugins_for_task(task_type, step_names)
        
        # 合并 LLM 显式指定的插件与注册表推导的插件
        analysis_plugins = list(set(analysis_plugins + inferred_analysis_plugins))

        thought = f"策略脑已规划 {len(plan)} 个步骤：" + " → ".join(s.get("step", "") for s in plan)
        if task_type:
            thought += f"；任务类型：{task_type}"
        thinking_logs = _append_thinking(base, "策略脑规划", thought)
        duration = round(time.perf_counter() - t0, 4)
        logger.info("planning_node 完成, duration=%.2fs, steps=%d", duration, len(plan))
        return {
            **base,
            "plan": plan,
            "task_type": task_type,
            "current_step": 0,
            "thinking_logs": thinking_logs,
            "step_outputs": [],
            "analysis_plugins": analysis_plugins,
            "generation_plugins": generation_plugins,
            "planning_duration_sec": duration,
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
            "kb_context": "",
            "analysis": {},
            "content": "",
            "evaluation": {},
        }
        
        step_outputs = []
        thinking_logs = list(base.get("thinking_logs") or [])

        # 可并行步骤：web_search、memory_query、bilibili_hotspot、kb_retrieve（无依赖）
        PARALLEL_STEPS = {"web_search", "memory_query", "bilibili_hotspot", "kb_retrieve"}
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
            if name == "bilibili_hotspot":
                return _run_bilibili_hotspot(sc)
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
            # 生成闲聊回复
            try:
                # 使用简单的 LLM 调用生成回复
                from langchain_core.messages import SystemMessage, HumanMessage
                reply_res = await llm.ainvoke([
                    SystemMessage(content="你是专业的营销AI助手。以自然、亲切、专业的口吻回复用户的闲聊（如问候、感谢等）。保持简短，引导用户进行营销相关的创作或分析。不要进行长篇大论。"),
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
                    # 计划中无 generate 时，输出策略方案而非单点切入点
                    plan_has_generate = any((s.get("step") or "").lower() == "generate" for s in plan)
                    strategy_mode = not plan_has_generate
                    
                    # 优先从步骤参数获取插件列表，其次从全局状态获取
                    step_plugins = params.get("analysis_plugins")
                    print(f"[DEBUG_META_PRINT] Step: {step_name}, Params: {params}, StepPlugins: {step_plugins}")
                    if isinstance(step_plugins, str):
                        step_plugins = [step_plugins]
                    analysis_plugins = step_plugins or base.get("analysis_plugins") or []
                    print(f"[DEBUG_META_PRINT] Final Analysis Plugins: {analysis_plugins}")
                    
                    plugin_input = {k: v for k, v in user_data.items() if k not in ("brand_name", "product_desc", "topic", "tags")}
                    plugin_input = plugin_input if plugin_input else None
                    analysis_result, cache_hit = await ai_svc.analyze(
                        request,
                        preference_context=preference_ctx,
                        context_fingerprint={"tags": context.get("effective_tags", []), "analysis_plugins": sorted(analysis_plugins)},
                        strategy_mode=strategy_mode,
                        analysis_plugins=analysis_plugins,
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
            eval_parts = [f"- 综合分：{evaluation.get('overall', 0)}/10"]
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
                user_data = {}
                if isinstance(user_input_str, str) and user_input_str.strip():
                    try:
                        user_data = json.loads(user_input_str)
                    except (TypeError, json.JSONDecodeError):
                        pass
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

        report_parts = [thinking_narrative_str, output_str]
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
        if suggested_next_plan is not None:
            out["suggested_next_plan"] = suggested_next_plan
        return out

    # ----- 调度与编排节点（多脑协同 + 动态闭环）-----
    PARALLEL_STEPS = {"web_search", "memory_query", "bilibili_hotspot", "kb_retrieve"}

    def _router_next(state: MetaState) -> str:
        """调度：根据 plan 与 current_step 决定下一节点。"""
        base = _ensure_meta_state(state)
        plan = base.get("plan") or []
        current = base.get("current_step") or 0
        if current >= len(plan):
            return "compilation"
        step = (plan[current].get("step") or "").lower()
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
            sn, params, reason = sc.get("step", ""), sc.get("params") or {}, sc.get("reason", "")
            query = params.get("query") or f"{brand} {product} {topic}".strip()
            results = await web_searcher.search(query, num_results=3)
            txt = web_searcher.format_results_as_context(results)
            return ({"step": sn, "reason": reason, "result": {"search_count": len(results), "summary": txt[:200]}}, f"已搜索「{query}」，获得 {len(results)} 条结果", {"search_results": txt})

        async def _run_memory_query(sc: dict) -> tuple[dict, str, dict]:
            """MemoryService 为唯一记忆源：三层记忆（品牌事实、用户画像、近期交互）"""
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            memory = await memory_svc.get_memory_for_analyze(user_id=base.get("user_id", ""), brand_name=brand, product_desc=product, topic=topic, tags_override=tags)
            mc = memory.get("preference_context", "")
            et = memory.get("effective_tags", [])
            return ({"step": sn, "reason": reason, "result": {"has_memory": bool(mc)}}, f"已查询用户记忆，{'有' if mc else '无'}历史偏好", {"memory_context": mc, "effective_tags": et})

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
            return ({"step": sn, "reason": reason, "result": {"passage_count": len(passages) if passages else 0}}, f"已检索知识库，获得 {len(passages) if passages else 0} 条相关段落", {"kb_context": txt})

        def _step_runner(sc: dict):
            name = (sc.get("step") or "").lower()
            if name == "web_search":
                return _run_web_search(sc)
            if name == "memory_query":
                return _run_memory_query(sc)
            if name == "bilibili_hotspot":
                return _run_bilibili_hotspot(sc)
            if name == "kb_retrieve":
                return _run_kb_retrieve(sc)
            return None

        tasks = [_step_runner(sc) for sc in parallel_plans]
        tasks = [t for t in tasks if t is not None]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
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
        search_context = "\n\n".join(search_parts) if search_parts else ""
        duration_par = round(time.perf_counter() - t0_par, 4)
        logger.info("parallel_retrieval_node 完成, duration=%.2fs, steps=%d", duration_par, len(parallel_plans))
        return {
            **base,
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

        # 提取当前步骤的 params，传入 analysis_plugins
        base = _ensure_meta_state(state)
        plan = base.get("plan") or []
        current = base.get("current_step") or 0
        analysis_plugins = []
        if current < len(plan):
            step_config = plan[current]
            params = step_config.get("params") or step_config.get("parameters") or {}
            analysis_plugins = params.get("analysis_plugins") or []
            
        # 更新 state 中的 analysis_plugins 供子图使用
        state_for_subgraph = {**state, "analysis_plugins": analysis_plugins}
        
        out = await analysis_subgraph.ainvoke(state_for_subgraph)
        duration_ana = round(time.perf_counter() - t0_ana, 4)
        logger.info("analyze_node 完成, duration=%.2fs", duration_ana)
        step_outputs = list(state.get("step_outputs") or [])
        step_outputs.append({"step": "analyze", "reason": "", "result": {"semantic_score": (out.get("analysis") or {}).get("semantic_score", 0), "angle": (out.get("analysis") or {}).get("angle", "")}})
        thinking_logs = _append_thinking({**state, "thinking_logs": state.get("thinking_logs") or []}, "analyze", f"分析完成，关联度 {(out.get('analysis') or {}).get('semantic_score', 0)}，切入点：{(out.get('analysis') or {}).get('angle', '')}")
        return {**out, "step_outputs": step_outputs, "thinking_logs": thinking_logs}

    async def generate_node(state: MetaState) -> dict:
        base = _ensure_meta_state(state)
        plan = base.get("plan") or []
        current = base.get("current_step") or 0
        params = (plan[current].get("params") or {}) if current < len(plan) else {}
        state_with_platform = {
            **state,
            "_generate_platform": params.get("platform", ""),
            "_generate_output_type": params.get("output_type", "text"),
        }
        out = await generation_subgraph.ainvoke(state_with_platform)
        step_outputs = list(state.get("step_outputs") or [])
        content = out.get("content", "")
        step_outputs.append({"step": "generate", "reason": "", "result": {"content_length": len(content), "preview": content[:150]}})
        thinking_logs = _append_thinking({**state, "thinking_logs": state.get("thinking_logs") or []}, "generate", f"已生成内容，长度 {len(content)} 字符")
        return {**out, "step_outputs": step_outputs, "thinking_logs": thinking_logs}

    async def evaluate_node(state: MetaState) -> dict:
        base = _ensure_meta_state(state)
        user_input_str = base.get("user_input") or ""
        try:
            user_data = json.loads(user_input_str) if isinstance(user_input_str, str) else {}
        except (TypeError, json.JSONDecodeError):
            user_data = {}
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
        thinking_logs = _append_thinking({**base, "thinking_logs": base.get("thinking_logs") or []}, "evaluate", f"评估完成，综合分 {evaluation.get('overall', 0)}，{'需修订' if need_revision else '通过'}")
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
        try:
            user_data = json.loads(user_input_str) if isinstance(user_input_str, str) else {}
        except (TypeError, json.JSONDecodeError):
            user_data = {}
        message = (user_data.get("raw_query") or "").strip()
        history_text = (user_data.get("conversation_context") or "").strip()
        if history_text:
            history_text = f"以下是近期对话：\n{history_text}\n\n"
        clarification_mode = user_data.get("has_ambiguous_feedback_after_creation") is True
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
        reply = await ai_svc.reply_casual(
            message=message,
            history_text=history_text,
            clarification_mode=clarification_mode,
            suggested_next_desc=suggested_next_desc,
            user_context=user_context,
        )
        step_outputs = list(base.get("step_outputs") or [])
        reason = "用户对生成内容评价合格但不满意，已引导指出问题或确认是否足够" if clarification_mode else "用户处于闲聊，直接回复"
        step_outputs.append({"step": "casual_reply", "reason": reason, "result": {"reply_length": len(reply or "")}})
        thinking_logs = _append_thinking(base, "闲聊回复", reason)
        plan = base.get("plan") or []
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

    workflow = StateGraph(MetaState)
    workflow.add_node("planning", planning_node)
    def router_node(state: MetaState) -> dict:
        """调度节点：仅透传 state，下一跳由 add_conditional_edges 的 _router_next 决定。"""
        return state
    workflow.add_node("router", router_node)
    workflow.add_node("parallel_retrieval", parallel_retrieval_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("evaluate", evaluate_node)
    workflow.add_node("human_decision", human_decision_node)
    workflow.add_node("skip", skip_node)
    workflow.add_node("casual_reply", casual_reply_node)
    workflow.add_node("compilation", compilation_node)

    workflow.set_entry_point("planning")
    workflow.add_edge("planning", "router")
    workflow.add_conditional_edges("router", _router_next, {"parallel_retrieval": "parallel_retrieval", "analyze": "analyze", "generate": "generate", "evaluate": "evaluate", "skip": "skip", "casual_reply": "casual_reply", "compilation": "compilation"})
    workflow.add_edge("parallel_retrieval", "router")
    workflow.add_edge("analyze", "router")
    workflow.add_edge("generate", "router")
    workflow.add_conditional_edges("evaluate", _eval_after_evaluate, {"human_decision": "human_decision", "router": "router"})
    workflow.add_conditional_edges("human_decision", _human_decision_next, {"generate": "generate", "router": "router"})
    workflow.add_edge("skip", "router")
    workflow.add_edge("casual_reply", "compilation")
    workflow.add_edge("compilation", END)

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

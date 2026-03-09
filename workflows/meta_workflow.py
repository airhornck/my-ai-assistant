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
from core.step_descriptions_for_planning import build_available_modules_section
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
        策略脑：根据用户意图构建思维链（Chain of Thought，CoT）
        保留原有思维链构建逻辑，同时优化意图识别与 generate 步骤处理。
        """
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        user_input = base.get("user_input") or ""

        # 尝试解析用户输入
        try:
            data = json.loads(user_input) if isinstance(user_input, str) else {}
        except (TypeError, json.JSONDecodeError):
            data = {}

        raw_query = (data.get("raw_query") or "").strip()
        intent = (data.get("intent") or "").strip()
        conversation_context = (data.get("conversation_context") or "").strip()
        explicit_content_request = False

        # 判断是否明确要求生成内容
        user_text = raw_query.lower()
        generation_keywords = ["生成", "写", "帮我写", "制定推广策略", "写文案", "生成文案", "写小红书", "写b站"]
        if any(k in user_text for k in generation_keywords):
            explicit_content_request = True
        elif data.get("explicit_content_request") is True:
            explicit_content_request = True
        # 采纳上轮建议且包含 generate，也视为明确生成
        suggested_plan = data.get("session_suggested_next_plan") or []
        if data.get("user_accepted_suggestion") and any(
            (s.get("step") or "").lower() == "generate" for s in suggested_plan if isinstance(s, dict)
        ):
            explicit_content_request = True

        brand = (data.get("brand_name") or "").strip()
        product = (data.get("product_desc") or "").strip()
        topic = (data.get("topic") or "").strip()
<<<<<<< feature/five

        # 构建系统指令：精简版专家原则
        system_prompt = """
你是策略规划专家，负责根据用户意图规划执行步骤。
- 严格判断是否需要 generate 步骤：仅当用户明确要求生成内容时才规划。
- 规划步骤可包含：web_search, memory_query, kb_retrieve, analyze, generate, evaluate。
- 闲聊或一般问答仅规划 casual_reply。
- 只输出 JSON 对象，不允许 Markdown 或额外文字。
- 输出格式：
  {"task_type": "...", "steps": [{"step": "...", "params": {}, "reason": "..."}, ...]}
=======
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

        available_modules = build_available_modules_section()
        system_prompt = f"""你是策略规划专家。**始终以专家原则进行规划**：根据用户意图判断需要哪些能力（检索、分析、生成等）来指导回答，充分利用现有能力；帮助客户厘清目标与缺失维度，必要时引导补充，若客户不补充则基于已有信息给出建议并生成，再通过后续建议与反馈迭代直至满意。不强行只规划一步生成，也不在信息不足时强行生成。

{available_modules}
可用模块（可扩展：注册自定义插件后，步骤名与注册名一致即可被编排执行）：
- web_search: 网络检索（竞品、热点、行业动态、通用信息）
- memory_query: 查询用户历史偏好与品牌事实
- kb_retrieve: 知识库检索（行业方法论、案例等，供分析/生成时更垂直、更专业；需要专业方案时可加入）
- industry_news_bilibili_rankings: 行业新闻与B站榜单分析（获取各行业热点和B站多榜单趋势）
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
5. 当用户明确指定B站/小破站/bilibili平台生成文案时，在analyze之前加入industry_news_bilibili_rankings步骤，用行业趋势和B站榜单指导生成。
6. 若用户要策略建议、竞品分析等，可只做 web_search + analyze，输出即建议。
7. 需要更垂直、专业的分析或方案时，可在 analyze 前加入 kb_retrieve 步骤（知识库检索）。
8. 信息不足时先搜索；有用户历史时查询记忆；步骤数 2-6 个为宜。
9. **改写请求**：当用户要求将「上文的已有内容」改写成某平台风格时，仍按专家原则选能力——先规划检索/分析（如B站用industry_news_bilibili_rankings获取行业趋势和B站榜单），再规划generate...
10. **采纳后续建议（继续创作）**：当用户采纳了上轮的「后续建议」时，表示**继续创作**意图。你会收到「建议的下一步」列表。若建议仅为 generate 且上文已有分析/内容，应**直接规划 generate（可加 evaluate）**，无需 web_search / memory_query / analyze，以体现继续创作意图；若建议含多步则按建议与专家判断执行。若当前缺少约束，在某步 reason 中注明需用户补充；若需结合当前热点再生成，可先加检索/分析再 generate。
11. **帮助客户实现目标（缺维度时的专家行为）**：当客户意图明确（如「生成文案」）但未补充关键维度时，你作为专家应仔细思考需要哪些维度才能达成目标。常见维度包括（可按任务类型增减）：**平台**（B站/小红书/抖音等）、**样式/体裁**（短视频脚本、图文、长文、口播稿等）、**长度**（字数或时长）、**目标人群**（年龄、兴趣、消费场景等）、**达成目标**（曝光/转化/种草/品牌认知等）、**调性/语气**（正式/轻松/幽默/专业等）、**卖点或核心信息**（要突出的产品卖点或品牌信息）、**禁忌/合规**（不能提的、敏感词）、**时效/节点**（节日、大促、热点等）。结合上下文与已有信息（品牌、产品、话题等）标出**已有维度**，在相应步骤的 reason 中**明确列出需客户补充的剩余维度**（如「需补充：平台、目标人群、期望长度」），引导客户只补缺失项；若客户表示不想补充（如「不用了」「直接生成吧」），则基于已有信息给出合理假设与建议，规划 analyze + generate，生成后再通过「后续建议」与评估/修订收集反馈，直至客户满意。
12. **闲聊与通用问答**：仅当用户当前输入**纯粹为闲聊**（问候、寒暄、无任何推广/生成/分析需求，如「你好」「还好」「在吗」）时，steps 仅为 [{"step": "casual_reply", "reason": "用户处于闲聊，直接回复"}]。若用户询问**与营销无关的通用问题**（如「当前时间」「今天几号」「明天是哪天」），也规划 [{"step": "casual_reply", "reason": "根据系统注入的当前日期时间直接回答"}]。若用户要**某赛道/品类的爆款文案、案例**（未明确是「帮我写一篇」）时，应规划 web_search（query 用用户原话或关键词，如「XX赛道 爆款文案」）+ analyze（根据检索结果整理回答），**不要**默认只输出「推广策略」；用户明确要求「生成/写」时再规划 generate。
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
{{"task_type": "campaign_or_copy", "steps": [
  {{"step": "industry_news_bilibili_rankings", "params": {{}}, "reason": "获取 B站热点结构与风格供借鉴"}},
  {{"step": "memory_query", "params": {{}}, "reason": "查询用户偏好"}},
  {{"step": "kb_retrieve", "params": {{}}, "reason": "检索知识库与案例"}},
  {{"step": "analyze", "params": {{}}, "reason": "分析品牌与热点关联"}},
  {{"step": "generate", "params": {{"platform": "B站"}}, "reason": "生成推广文案"}},
  {{"step": "evaluate", "params": {{}}, "reason": "评估内容质量"}}
]}}

```

示例（对上文内容改写成 B站风格，须先检索/分析再改写）：
```json
{{"task_type": "campaign_or_copy", "steps": [
  {{"step": "industry_news_bilibili_rankings", "params": {{}}, "reason": "获取 B站当前热点与风格供改写借鉴"}},
  {{"step": "analyze", "params": {{}}, "reason": "结合热点与上文内容提炼改写方向"}},
  {{"step": "generate", "params": {{"platform": "B站", "output_type": "rewrite"}}, "reason": "将上文内容改写成 B站风格"}},
  {{"step": "evaluate", "params": {{}}, "reason": "评估改写稿质量"}}
]}}
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
>>>>>>> main
"""

        # 构建用户 Prompt
        user_prompt = f"""
用户信息：
- 品牌：{brand or "未指定"}
- 产品：{product or "未指定"}
- 话题/目标：{topic or raw_query or "未指定"}
- 原始意图：{intent or "未指定"}
- 是否明确要求生成：{"是" if explicit_content_request else "否"}

用户上下文：
{conversation_context[:600] if conversation_context else ""}

请按照专家原则规划最合理的步骤：
- 如果明确要求生成，请包含 generate（params 可根据 rewrite_previous_for_platform 注入 output_type/platform）。
- 如果未明确生成，请规划 web_search + analyze + casual_reply 来引导用户。
- 对闲聊仅规划 casual_reply。
- 规划思维链，标出每步 reason。
- 保持步骤 2~6 步为宜。
"""

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

        # 调用 LLM
        try:
            response = await llm.invoke(messages, task_type="planning", complexity="high")
            raw = response.strip()
            for prefix in ("```json", "```"):
                if raw.startswith(prefix):
                    raw = raw[len(prefix):].strip()
            if raw.endswith("```"):
                raw = raw[:raw.rfind("```")].strip()
            parsed = json.loads(raw)
            plan = parsed.get("steps", []) if isinstance(parsed, dict) else []
            task_type = parsed.get("task_type", "") if isinstance(parsed, dict) else ""
        except Exception:
            # 兜底 plan
            if explicit_content_request:
                plan = [
                    {"step": "analyze", "params": {}, "reason": "分析品牌与话题"},
                    {"step": "generate", "params": {}, "reason": "生成推广文案"},
                    {"step": "evaluate", "params": {}, "reason": "评估内容质量"},
                ]
                task_type = "campaign_or_copy"
            else:
                plan = [
                    {"step": "web_search", "params": {"query": raw_query or topic or brand}, "reason": "检索用户问题相关信息"},
                    {"step": "analyze", "params": {}, "reason": "根据检索结果回答用户问题"},
                ]
                task_type = "campaign_or_copy"

        # 安全过滤：未明确要求生成时移除 generate 步骤
        if not explicit_content_request:
            plan = [s for s in plan if (s.get("step") or "").lower() != "generate"]

        # 空 plan 兜底：解析成功但得到空列表时，按 explicit 补 2 步（与旧版一致）
        if not plan:
            if explicit_content_request:
                plan = [
                    {"step": "analyze", "params": {}, "reason": "分析品牌与话题"},
                    {"step": "generate", "params": {}, "reason": "生成推广文案"},
                ]
                task_type = "campaign_or_copy"
            else:
                plan = [
                    {"step": "web_search", "params": {"query": raw_query or topic or brand or "相关信息"}, "reason": "检索用户问题相关信息"},
                    {"step": "analyze", "params": {}, "reason": "根据检索结果回答用户问题"},
                ]
                task_type = "campaign_or_copy"

        # 构建思维链日志
        thought = f"策略脑规划 {len(plan)} 个步骤：" + " → ".join(s.get("step", "") for s in plan)
        thinking_logs = _append_thinking(base, "策略脑规划", thought)

        duration = round(time.perf_counter() - t0, 4)
        return {
            **base,
            "plan": plan,
            "task_type": task_type,
            "current_step": 0,
            "thinking_logs": thinking_logs,
            "step_outputs": [],
            "analysis_plugins": [],
            "generation_plugins": [],
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
                    strategy_mode = not plan_has_generate and not answer_from_search
                    
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
                        strategy_mode=strategy_mode,
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
                    thought = "已根据检索结果回答" if answer_from_search else ("分析完成，已输出推广策略" if strategy_mode else f"分析完成，关联度 {analysis_result.get('semantic_score', 0)}，切入点：{analysis_result.get('angle', '')}")
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
            sn, reason = sc.get("step", ""), sc.get("reason", "")
            params = _complete_step_params("web_search", sc.get("params") or {}, user_data)
            query = (params.get("query") or "").strip() or f"{brand} {product} {topic}".strip()
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
                    return ({"step": sn, "reason": reason, "result": {"skipped": "no_kb"}}, "未配置知识库，跳过", {})
            query = (params.get("query") or "").strip() or f"{brand} {product} {topic}".strip() or "营销策略"
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

    def _planning_shortcut_next(state: MetaState) -> str:
        """进入 planning 前短路：若已走 shortcut 则直接进 router，否则进 planning。"""
        return "router" if state.get("_from_planning_shortcut") else "planning"

    async def planning_shortcut_node(state: MetaState) -> dict:
        """进入 planning 前短路：极短闲聊、模糊评价直接组 1 步 casual_reply，跳过 LLM 规划（与旧版对齐）。"""
        t0 = time.perf_counter()
        base = _ensure_meta_state(state)
        user_input = base.get("user_input") or ""
        try:
            data = json.loads(user_input) if isinstance(user_input, str) else {}
        except (TypeError, json.JSONDecodeError):
            data = {}
        raw_query = (data.get("raw_query") or "").strip()
        # 极短闲聊：与 processor 一致，直接 casual_reply
        try:
            from core.intent.processor import SHORT_CASUAL_REPLIES
            if raw_query in SHORT_CASUAL_REPLIES and len(raw_query) <= 8:
                plan = [{"step": "casual_reply", "params": {}, "reason": "用户处于闲聊，直接回复"}]
                thought = "用户处于闲聊，规划一步 casual_reply"
                thinking_logs = _append_thinking(base, "策略脑规划", thought)
                duration = round(time.perf_counter() - t0, 4)
                logger.info("planning_shortcut: 极短闲聊，跳过 LLM, raw=%s", raw_query)
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
            logger.info("planning_shortcut: 模糊评价短路，跳过 LLM")
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
                "_from_planning_shortcut": True,
            }
        return {**base}

    workflow = StateGraph(MetaState)
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
        # 根据 task_type 与 plan 推断 analysis_plugins / generation_plugins（与旧版对齐）
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

    workflow.set_entry_point("planning_shortcut")
    workflow.add_conditional_edges("planning_shortcut", _planning_shortcut_next, {"router": "router", "planning": "planning"})
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

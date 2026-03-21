"""
AI 服务门面：组合 core/ai 与 domain/content，保持对外 API 稳定。
支持注入不同 ILLMClient 实现以替换 AI 供应商。

配置来源：config.api_config，经 DashScopeLLMClient 使用 intent/strategy/analysis/evaluation 接口；
ContentGenerator 使用 generation_text 接口。
"""
from __future__ import annotations

import logging
import random
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from cache.smart_cache import SmartCache, build_analyze_cache_key, TTL_AI_DEFAULT, TTL_ANALYSIS_WITH_PLUGINS
from core.ai import DashScopeLLMClient, ILLMClient
from core.brain_plugin_center import BrainPluginCenter
from domain.content import ContentAnalyzer, ContentEvaluator, ContentGenerator
from models.request import ContentRequest

logger = logging.getLogger(__name__)

CACHE_TTL_JITTER = 60


class SimpleAIService:
    """
    AI 服务门面：整合分析、生成、评估、闲聊。
    可注入 llm_client 替换 AI 供应商，注入 cache 加速高频请求。
    """

    def __init__(
        self,
        cache: Optional[SmartCache] = None,
        llm_client: Optional[ILLMClient] = None,
        router_config: Optional[dict] = None,
        methodology_service: Any = None,
        case_service: Any = None,
        knowledge_port: Any = None,
        methodology_plugin: Optional[dict] = None,
        case_library_plugin: Optional[dict] = None,
        knowledge_base_plugin: Optional[dict] = None,
        campaign_plan_generator: Optional[dict] = None,
        multimodal_port: Any = None,
        prediction_port: Any = None,
        video_decomposition_port: Any = None,
        sample_library: Any = None,
        platform_rules: Any = None,
        memory_service: Any = None,
        db_session_factory: Any = None,
        plugin_bus: Any = None,
    ) -> None:
        self._llm = llm_client or DashScopeLLMClient(router_config or {})
        self._cache = cache
        self._analyzer = ContentAnalyzer(self._llm)
        self._generator = ContentGenerator(self._llm)
        self._evaluator = ContentEvaluator(self._llm)

        # 分析脑插件中心：按 ANALYSIS_BRAIN_PLUGINS 清单加载插件并启动定时任务
        from core.brain_plugin_center import ANALYSIS_BRAIN_PLUGINS, GENERATION_BRAIN_PLUGINS
        analysis_config = {
            "cache": cache,
            "smart_cache": cache,  # 别名，兼容插件内 config.get("smart_cache")
            "ai_service": self,
            "memory_service": memory_service,
            "db_session_factory": db_session_factory,
            "plugin_bus": plugin_bus,
            "methodology_service": methodology_service,
            "case_service": case_service,
            "knowledge_port": knowledge_port,
            "methodology_plugin": methodology_plugin or {},
            "case_library_plugin": case_library_plugin or {},
            "knowledge_base_plugin": knowledge_base_plugin or {},
            # 五能力：按需调用，不进入主流程；未注入时插件可降级
            "multimodal_port": multimodal_port,
            "prediction_port": prediction_port,
            "video_decomposition_port": video_decomposition_port,
            "sample_library": sample_library,
            "platform_rules": platform_rules,
        }
        self._analysis_plugin_center = BrainPluginCenter("analysis", analysis_config)
        BrainPluginCenter.load_plugins_for_brain(
            "analysis",
            self._analysis_plugin_center,
            analysis_config,
            ANALYSIS_BRAIN_PLUGINS,
        )
        self._analyzer.plugin_center = self._analysis_plugin_center
        self._analysis_plugin_center.start_scheduled_tasks()

        # 生成脑插件中心：按 GENERATION_BRAIN_PLUGINS 清单加载插件；模型配置由插件中心管理
        try:
            from config.api_config import get_model_config
            _gen_text_cfg = get_model_config("generation_text")
        except Exception:
            _gen_text_cfg = {}
        gen_config = {
            "cache": cache,
            "ai_service": self,
            "campaign_plan_generator": campaign_plan_generator or {},
            "models": {
                "text_generator": _gen_text_cfg,
                "campaign_plan_generator": _gen_text_cfg,
            },
        }
        self._generation_plugin_center = BrainPluginCenter("generation", gen_config)
        BrainPluginCenter.load_plugins_for_brain(
            "generation",
            self._generation_plugin_center,
            gen_config,
            GENERATION_BRAIN_PLUGINS,
        )
        self._generator.plugin_center = self._generation_plugin_center

        # 兼容旧用法：router 供外部 route() 调用（如 intent、campaign_planner 需要）
        self.router = _RouterAdapter(self._llm)
        self.client = self.router  # 别名，兼容 plugin/campaign_planner 中 ai_svc.client

    async def reply_casual(
        self,
        message: str,
        history_text: str = "",
        clarification_mode: bool = False,
        clarification_kind: str = "",
        clarification_question: str = "",
        suggested_next_desc: str = "",
        user_context: str = "",
    ) -> str:
        """日常闲聊/澄清回复。user_context 为 UserProfile 摘要，用于回答「我是谁」等身份问题。"""
        if clarification_mode:
            kind = (clarification_kind or "").strip().lower()
            if kind == "intent_unclear":
                q = (clarification_question or "").strip()
                if not q:
                    q = "你更想要我给你“可直接用的内容”，还是“先分析再给建议”？另外目标平台/受众/语气有没有偏好？"
                prompt = f"""{history_text}用户最新消息：{message}

你是 AI 营销助手。用户的需求表达还不够具体，但你应该尽量顺着聊下去，不要拷问式追问。

请用自然、体贴、专业的口吻回复 2-4 句，做到：
1) 先用一句话复述你理解到的方向（不要装作很确定）
2) 给出一个你可以立刻提供的“默认帮助”（比如先给 3 个方向/一份大纲/一个简短建议）
3) 只问 1 个最关键的澄清问题（优先问产出类型/平台/受众/语气四者之一）

你要问的关键问题（可直接复用或自然改写）：{q}
不要输出列表编号，不要说“请提供以下信息”。"""
            else:
                # 默认：生成内容后的模糊评价澄清
                prompt = f"""{history_text}用户最新消息：{message}

你是 AI 营销助手。用户对上一轮生成的创作内容给出了模糊评价（如「还不错」「还行」「还好吧」），表示合格但可能不太满意。

请生成 1-2 句引导性回复，帮助用户：(1) 指出哪些地方需要调整，或 (2) 确认当前内容是否已经足够。语气自然、体贴。
示例：「你觉得哪些地方需要调整？还是说这样就可以了？」

若上轮有后续建议（如：{suggested_next_desc or '无'}），可简短提及作为备选，但主导向应是「指出问题」或「确认足够」。"""
        else:
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            cn_now = now + timedelta(hours=8)  # 东八区，便于回答「当前时间」「今天几号」「明天是哪天」
            weekday_cn = ["一", "二", "三", "四", "五", "六", "日"]
            date_time_str = cn_now.strftime(f"%Y年%m月%d日 %H:%M 星期{weekday_cn[cn_now.weekday()]}")
            ctx_block = f"\n已知用户信息：{user_context}\n" if user_context else ""
            prompt = f"""{history_text}{ctx_block}【参考·当前日期与时间】{date_time_str}（仅当用户明确问「今天几号」「明天是哪天」「当前时间」等时才用此回答；其他问题不要报日期。）

用户最新消息：{message}

你是 AI 营销助手，当前用户处于日常聊天状态。请简短、友好地回复，1-3 句话即可。
【重要】仅当用户明确询问日期/时间/今天/明天/星期几时，才根据【参考·当前日期与时间】回答；问候、营销需求、其他闲聊等一律正常回复，不要主动提日期。
若上文有近期对话，用户询问「刚才/之前说了什么」「我喜欢什么」等，必须根据近期对话内容回答。
若用户询问身份/品牌/行业（如「我是谁」「你还记得我吗」），结合已知用户信息自然回答。"""
        messages = [HumanMessage(content=prompt)]
        return await self._llm.invoke(messages, task_type="chat_reply", complexity="low")

    async def analyze(
        self,
        request: ContentRequest,
        preference_context: Optional[str] = None,
        context_fingerprint: Optional[dict] = None,
        answer_from_search: bool = False,
        analysis_plugins: Optional[list] = None,
        plugin_input: Optional[dict] = None,
    ) -> tuple[dict[str, Any], bool]:
        """分析品牌与热点关联度，支持缓存。answer_from_search 时根据检索结果直接回答。插件列表由 plan 指定。"""
        if answer_from_search:
            result = await self._analyzer.analyze(
                request, preference_context, answer_from_search=True,
                plugin_input=plugin_input,
            )
            return result, False
        fp = dict(context_fingerprint or {})
        if analysis_plugins:
            fp["analysis_plugins"] = sorted(analysis_plugins)
        key = build_analyze_cache_key(
            user_id=request.user_id or "",
            brand_name=request.brand_name or "",
            product_desc=request.product_desc or "",
            topic=request.topic or "",
            context_fingerprint=fp,
        )
        if self._cache is not None:
            ttl = (TTL_ANALYSIS_WITH_PLUGINS + random.randint(-30, 30)) if analysis_plugins else (TTL_AI_DEFAULT + random.randint(-CACHE_TTL_JITTER, CACHE_TTL_JITTER))
            _pi = plugin_input
            result, hit = await self._cache.get_or_set(
                key,
                lambda: self._analyzer.analyze(
                    request, preference_context, analysis_plugins=analysis_plugins, plugin_input=_pi,
                ),
                ttl=ttl,
            )
            logger.info("analyze 缓存 %s key=%s", "命中" if hit else "未命中", key)
            return result, hit
        result = await self._analyzer.analyze(
            request, preference_context, analysis_plugins=analysis_plugins, plugin_input=plugin_input,
        )
        return result, False

    async def evaluate_content(self, content: str, context: dict) -> dict[str, Any]:
        """评估生成内容，四维度打分。"""
        return await self._evaluator.evaluate(content, context)

    async def generate(
        self,
        analysis: str | dict[str, Any],
        topic: str = "",
        raw_query: str = "",
        session_document_context: str = "",
        output_type: str = "text",
        generation_plugins: Optional[list] = None,
        memory_context: str = "",
        source_content: Optional[str] = None,
    ) -> str:
        """按 output_type 生成内容（text/image/video）；source_content 非空且 output_type=rewrite 时为对上文的风格改写。"""
        return await self._generator.generate(
            analysis,
            topic=topic,
            raw_query=raw_query,
            session_document_context=session_document_context,
            output_type=output_type,
            generation_plugins=generation_plugins,
            memory_context=memory_context,
            source_content=source_content,
        )


class _RouterAdapter:
    """兼容旧代码中 ai.router.route() 的调用，供 core/intent 等使用。"""

    def __init__(self, llm: ILLMClient) -> None:
        self._llm = llm
        self._task = "chat"
        self._complexity = "medium"
        self.fast_model = self
        self.powerful_model = self

    async def route(self, task_type: str, prompt_complexity: str) -> "_RouterAdapter":
        self._task = task_type
        self._complexity = prompt_complexity
        return self

    async def ainvoke(self, messages) -> Any:
        """供 LangChain 格式调用。"""
        text = await self._llm.invoke(messages, task_type=self._task, complexity=self._complexity)
        return _FakeResponse(text)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = text

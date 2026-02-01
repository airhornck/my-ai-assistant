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

from cache.smart_cache import SmartCache, build_analyze_cache_key, TTL_AI_DEFAULT
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
    ) -> None:
        self._llm = llm_client or DashScopeLLMClient(router_config or {})
        self._cache = cache
        self._analyzer = ContentAnalyzer(self._llm)
        self._generator = ContentGenerator(self._llm)
        self._evaluator = ContentEvaluator(self._llm)

        # 分析脑插件中心：按 ANALYSIS_BRAIN_PLUGINS 清单加载插件并启动定时任务
        from core.brain_plugin_center import ANALYSIS_BRAIN_PLUGINS
        self._analysis_plugin_center = BrainPluginCenter("analysis", {"cache": cache, "ai_service": self})
        BrainPluginCenter.load_plugins_for_brain(
            "analysis",
            self._analysis_plugin_center,
            {"cache": cache, "ai_service": self},
            ANALYSIS_BRAIN_PLUGINS,
        )
        self._analyzer.plugin_center = self._analysis_plugin_center
        self._analysis_plugin_center.start_scheduled_tasks()
        # 兼容旧用法：router 供外部 route() 调用（如 intent、campaign_planner 需要）
        self.router = _RouterAdapter(self._llm)
        self.client = self.router  # 别名，兼容 plugin/campaign_planner 中 ai_svc.client

    async def reply_casual(self, message: str, history_text: str = "") -> str:
        """日常闲聊回复。"""
        prompt = f"""{history_text}用户最新消息：{message}

你是 AI 营销助手，当前用户处于日常聊天状态。请简短、友好地回复，1-3 句话即可。"""
        messages = [HumanMessage(content=prompt)]
        return await self._llm.invoke(messages, task_type="chat_reply", complexity="low")

    async def analyze(
        self,
        request: ContentRequest,
        preference_context: Optional[str] = None,
        context_fingerprint: Optional[dict] = None,
        strategy_mode: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        """分析品牌与热点关联度，支持缓存。strategy_mode 时输出推广策略方案。"""
        if strategy_mode:
            result = await self._analyzer.analyze(request, preference_context, strategy_mode=True)
            return result, False
        key = build_analyze_cache_key(
            user_id=request.user_id or "",
            brand_name=request.brand_name or "",
            product_desc=request.product_desc or "",
            topic=request.topic or "",
            context_fingerprint=context_fingerprint or {},
        )
        if self._cache is not None:
            ttl = TTL_AI_DEFAULT + random.randint(-CACHE_TTL_JITTER, CACHE_TTL_JITTER)
            result, hit = await self._cache.get_or_set(
                key,
                lambda: self._analyzer.analyze(request, preference_context),
                ttl=ttl,
            )
            logger.info("analyze 缓存 %s key=%s", "命中" if hit else "未命中", key)
            return result, hit
        result = await self._analyzer.analyze(request, preference_context)
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
    ) -> str:
        """按 output_type 生成内容（text/image/video）。"""
        return await self._generator.generate(
            analysis,
            topic=topic,
            raw_query=raw_query,
            session_document_context=session_document_context,
            output_type=output_type,
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

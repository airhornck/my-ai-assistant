"""
分析脑：品牌与热点关联度分析，输出结构化 JSON。
由工作流按 plan 中的 analyze 步骤及指定插件列表调用；analysis_plugins 由策略脑（Planning Agent）规划，不硬编码。
不输出推广策略方案，推广策略由 Planning Agent 规划步骤 + 生成脑插件实现。
支持按 analysis_plugins 并行执行插件并合并结果，单插件超时保障体验。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, List, Optional, TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from models.request import ContentRequest

if TYPE_CHECKING:
    from core.ai.port import ILLMClient
    from core.brain_plugin_center import BrainPluginCenter

logger = logging.getLogger(__name__)

# 单插件执行超时（秒），避免拖死整体
PLUGIN_RUN_TIMEOUT = 90

DEFAULT_ANALYSIS_DICT = {
    "semantic_score": 0,
    "angle": "暂无推荐切入点",
    "reason": "分析结果解析失败，请重试。",
}


class ContentAnalyzer:
    """分析脑：调用 LLM 分析品牌与热点关联度。含脑级插件中心，扩展分析能力。"""

    def __init__(
        self,
        llm_client: "ILLMClient",
        plugin_center: "BrainPluginCenter | None" = None,
    ) -> None:
        self._llm = llm_client
        self.plugin_center = plugin_center

    async def analyze(
        self,
        request: ContentRequest,
        preference_context: Optional[str] = None,
        answer_from_search: bool = False,
        analysis_plugins: Optional[List[str]] = None,
        plugin_input: Optional[dict] = None,
    ) -> dict[str, Any]:
        """分析品牌与热点关联度，返回 semantic_score、angle、reason。
        
        推广策略由 PlanningAgent 规划步骤与插件，由 generate 步骤调用生成脑插件输出，本模块不再输出推广策略方案。
        answer_from_search=True 时根据检索结果直接回答用户问题。
        analysis_plugins 由 plan 指定，非空时并行执行这些插件并合并结果（单插件超时）。"""
        if answer_from_search and preference_context:
            return await self._answer_from_search(request, preference_context, plugin_input or {})
        
        user_prompt = f"""请根据以下信息，分析品牌与热点话题的关联度，并给出推荐切入点和理由。

【本次请求】
品牌名称：{request.brand_name}
产品描述：{request.product_desc}
热点话题：{request.topic}
"""
        if preference_context:
            user_prompt += f"""
【用户长期记忆 / 历史画像与过往交互偏好】（含近期交互，请优先参考以保持连贯与个性化）
{preference_context}
"""
        user_prompt += """

请只输出一个 JSON 对象，不要有任何其他文本、说明或 markdown 标题。
必须用三个反引号包裹，格式为：```json
{ ... }
```

JSON 必须至少包含以下字段（类型与含义不可变）：
- semantic_score：整数，0-100，表示品牌与热点的语义关联度
- angle：字符串，推荐的营销切入点或创意角度
- reason：字符串，简要分析理由（可结合用户历史偏好说明）

只输出 JSON，不要有任何其他文本。"""

        messages = [
            SystemMessage(content="你是一位资深营销顾问，请综合用户的历史画像和过往交互偏好进行本次分析，确保建议的连贯性和个性化。"),
            HumanMessage(content=user_prompt),
        ]
        raw = await self._llm.invoke(messages, task_type="analysis", complexity="medium")

        for prefix in ("```json", "```"):
            if raw.startswith(prefix):
                raw = raw[len(prefix) :].strip()
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")].strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("analyze JSON 解析失败: %s raw=%s", e, raw[:500])
            data = {}

        if not isinstance(data, dict):
            data = {}

        result = {
            "semantic_score": data.get("semantic_score", 0),
            "angle": data.get("angle", ""),
            "reason": data.get("reason", ""),
        }
        # 按 analysis_plugins 并行执行插件并合并（单插件超时，不阻塞主分析）
        if analysis_plugins and self.plugin_center:
            ctx = {
                "request": request,
                "preference_context": preference_context,
                "analysis": result,
                "plugin_input": plugin_input or {},
            }
            plugin_results = await self._run_analysis_plugins(analysis_plugins, ctx)
            for name, out in plugin_results.items():
                if out and isinstance(out, dict):
                    # 插件返回 {"analysis": {key: value}} 时合并到 result，否则 result[name]=out
                    if "analysis" in out and isinstance(out.get("analysis"), dict):
                        for k, v in out["analysis"].items():
                            result[k] = v
                    else:
                        result[name] = out
        return result

    async def _run_analysis_plugins(
        self,
        plugin_names: List[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """并行执行分析插件，单插件超时，失败降级为空。"""
        logger.debug("_run_analysis_plugins called with: %s", plugin_names)
        if self.plugin_center:
            logger.debug("Plugin center loaded plugins: %s", list(self.plugin_center._plugins.keys()))
        else:
            logger.debug("No plugin center!")

        async def run_one(name: str) -> tuple[str, dict]:
            try:
                out = await asyncio.wait_for(
                    self.plugin_center.get_output(name, context),
                    timeout=PLUGIN_RUN_TIMEOUT,
                )
                return (name, out if isinstance(out, dict) else {})
            except asyncio.TimeoutError:
                logger.warning("分析插件 %s 超时（%ss）", name, PLUGIN_RUN_TIMEOUT)
                return (name, {})
            except Exception as e:
                logger.warning("分析插件 %s 失败: %s", name, e)
                return (name, {})

        if not plugin_names or not self.plugin_center:
            return {}
        tasks = [run_one(n) for n in plugin_names if self.plugin_center.has_plugin(n)]
        if not tasks:
            return {}
        done = await asyncio.gather(*tasks)
        return dict(done)

    async def _answer_from_search(
        self,
        request: ContentRequest,
        preference_context: str,
        plugin_input: dict,
    ) -> dict[str, Any]:
        """根据检索结果直接回答用户问题，不输出推广策略。返回 angle=回复正文。"""
        raw_query = (plugin_input.get("raw_query") or request.topic or "").strip() or "上述问题"
        user_prompt = f"""【网络检索信息】
{preference_context}

【用户问题】
{raw_query}

请根据上述检索信息，直接、简洁地回答用户问题。整理成 1～3 段易读的正文即可，不要输出「推广策略」「渠道建议」等营销方案，不要输出 JSON。若检索内容与问题相关度低，可简要说明并建议用户换个问法或补充信息。"""
        messages = [
            SystemMessage(content="你根据检索结果直接回答用户问题，语气自然、简洁。不要输出推广策略或方案。"),
            HumanMessage(content=user_prompt),
        ]
        raw = await self._llm.invoke(messages, task_type="analysis", complexity="medium")
        text = (raw.strip() if isinstance(raw, str) else str(raw)) or "暂无相关检索结果，请换个关键词试试。"
        return {
            "semantic_score": 0,
            "angle": text,
            "reason": "已根据检索结果回答",
        }

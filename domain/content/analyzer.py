"""
分析脑：品牌与热点关联度分析，输出结构化 JSON。
可单独开发与测试，依赖 ILLMClient 注入。
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
PLUGIN_RUN_TIMEOUT = 5

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
        strategy_mode: bool = False,
        analysis_plugins: Optional[List[str]] = None,
    ) -> dict[str, Any]:
        """分析品牌与热点关联度，返回 semantic_score、angle、reason。
        strategy_mode=True 时输出推广策略方案。analysis_plugins 非空时并行执行这些插件并合并结果（单插件超时）。"""
        if strategy_mode:
            return await self._analyze_strategy(request, preference_context, analysis_plugins=analysis_plugins)
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
            plugin_results = await self._run_analysis_plugins(
                analysis_plugins,
                {
                    "request": request,
                    "preference_context": preference_context,
                    "analysis": result,
                },
            )
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

    async def _analyze_strategy(
        self,
        request: ContentRequest,
        preference_context: Optional[str] = None,
        analysis_plugins: Optional[List[str]] = None,
    ) -> dict[str, Any]:
        """策略模式：输出推广策略方案（渠道、内容方向、人群细分），类似顾问建议。"""
        user_prompt = f"""请根据以下信息，输出针对该品牌/产品的推广策略方案。**不要生成具体文案**，只输出策略、渠道、内容方向和人群细分建议。

【本次请求】
品牌名称：{request.brand_name}
产品描述：{request.product_desc}
热点话题/目标：{request.topic}
"""
        if preference_context:
            user_prompt += f"""
【用户历史偏好】
{preference_context}
"""
        user_prompt += """

请输出结构化的推广策略，包含：
1. 人群细分（如 18-24 vs 25-35 的不同诉求）
2. 核心差异化卖点
3. 渠道建议（线上/线下、具体平台）
4. 内容方向（种草、测评、场景化等）
5. 可选的转化钩子（优惠、以旧换新等）

用清晰的段落或 bullet 形式输出，类似顾问给出的方案，便于用户参考后决定下一步（如是否生成具体文案）。不要输出成品文案。"""

        messages = [
            SystemMessage(content="你是一位资深营销顾问，擅长制定推广策略。请输出方案型内容，不要生成具体文案。"),
            HumanMessage(content=user_prompt),
        ]
        raw = await self._llm.invoke(messages, task_type="analysis", complexity="high")
        # 策略模式返回 angle=完整策略文本，reason=简要说明
        result = {
            "semantic_score": 85,
            "angle": raw.strip() if isinstance(raw, str) else str(raw),
            "reason": "已完成，可参考建议进行改善",
        }
        if analysis_plugins and self.plugin_center:
            plugin_results = await self._run_analysis_plugins(
                analysis_plugins,
                {"request": request, "preference_context": preference_context, "analysis": result},
            )
            for name, out in plugin_results.items():
                if out and isinstance(out, dict):
                    if "analysis" in out and isinstance(out.get("analysis"), dict):
                        for k, v in out["analysis"].items():
                            result[k] = v
                    else:
                        result[name] = out
        return result


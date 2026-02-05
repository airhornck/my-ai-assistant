"""
评估脑：对生成内容多维度打分并给出专家式质量评估。
质量评估说明：本文参考了什么（如引用的插件能力）、具备哪些热点特征、适合发布在哪些平台等。
"""
from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
    from core.ai.port import ILLMClient

logger = logging.getLogger(__name__)

DEFAULT_EVALUATION = {
    "scores": {"consistency": 5, "creativity": 5, "safety": 5, "platform_fit": 5},
    "overall": 5.0,
    "suggestions": "评估服务暂时不可用，已使用默认结果，主流程继续。",
    "quality_assessment": "",
    "overall_score": 5,
    "evaluation_failed": True,
}


class ContentEvaluator:
    """评估脑：对推广内容四维度打分并给出专家式质量评估（参考来源、热点特征、适合平台等）。"""

    def __init__(self, llm_client: "ILLMClient") -> None:
        self._llm = llm_client

    async def evaluate(self, content: str, context: dict[str, Any]) -> dict[str, Any]:
        """
        四维度打分 + 专家式质量评估说明。
        返回 scores、overall、suggestions、quality_assessment、overall_score。
        quality_assessment：专家判断，说明本文参考了什么、具备哪些热点特征、适合哪些平台等。
        """
        default = DEFAULT_EVALUATION.copy()
        brand_name = context.get("brand_name", "")
        topic = context.get("topic", "")
        analysis_summary = context.get("analysis", "")
        steps_used = context.get("steps_used", "") or "未提供"
        if isinstance(analysis_summary, dict):
            analysis_summary = (
                f"关联度：{analysis_summary.get('semantic_score', '')}；切入点：{analysis_summary.get('angle', '')}；"
                f"理由：{analysis_summary.get('reason', '')}"
            ) if analysis_summary else "无"

        system_prompt = (
            "你是一位营销文案评审专家。对推广内容做四维度打分，并输出一段**质量评估**（专家判断），"
            "说明：本文参考了哪些能力或数据（如检索、B站热点、分析结论等）、具备哪些热点/趋势特征、"
            "适合发布在哪些平台、与品牌目标的契合度等。必须只输出一个纯 JSON 对象，不要其他文字。"
        )
        user_prompt = f"""请对以下推广内容从四个维度打分（每项 1-10 分），并给出一段**质量评估**（专家判断，非改进建议）。

【待评估内容】
{content[:2000]}

【本次请求 / 上下文】
品牌名称：{brand_name}
热点/主题：{topic}
分析摘要：{analysis_summary or "无"}
本轮参考的能力/步骤：{steps_used}

【四个维度打分】
1. consistency（与品牌目标的一致性）
2. creativity（创意度）
3. safety（语言风险/合规）
4. platform_fit（平台风格契合度）

【质量评估】请写一段专家判断（quality_assessment），包含：本文参考了什么（如引用的插件/能力）、具备哪些热点或趋势特征、适合发布在哪些平台、整体质量简要结论。不要写成「改进建议」列表，而是成段的专家评估说明。

【输出格式】只输出一个纯 JSON 对象，示例：
{{"scores": {{"consistency": 8, "creativity": 9, "safety": 9, "platform_fit": 8}}, "overall": 8.5, "quality_assessment": "本文参考了 B站热点与品牌分析结论，具备…特征，适合在 B站、小红书等平台发布。…"}}

- scores：必须包含 consistency、creativity、safety、platform_fit，均为整数 1-10
- overall：综合分，数字
- quality_assessment：字符串，一段专家式质量评估（参考来源、热点特征、适合平台等），非改进建议

只输出 JSON。"""

        try:
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            raw = await self._llm.invoke(messages, task_type="evaluation", complexity="medium")

            for prefix in ("```json", "```"):
                if raw.startswith(prefix):
                    raw = raw[len(prefix) :].strip()
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")].strip()

            data = json.loads(raw)
            if not isinstance(data, dict):
                return default

            scores = data.get("scores") or {}
            overall = data.get("overall", 0)
            try:
                overall = float(overall)
            except (TypeError, ValueError):
                overall = 0.0
            overall = max(0.0, min(10.0, overall))
            overall_score = int(round(overall))
            quality_assessment = (data.get("quality_assessment") or "").strip()
            suggestions = data.get("suggestions", "") or default["suggestions"]

            return {
                "scores": {
                    "consistency": scores.get("consistency", 0),
                    "creativity": scores.get("creativity", 0),
                    "safety": scores.get("safety", 0),
                    "platform_fit": scores.get("platform_fit", 0),
                },
                "overall": round(overall, 1),
                "suggestions": suggestions,
                "quality_assessment": quality_assessment or suggestions,
                "overall_score": overall_score,
            }
        except json.JSONDecodeError as e:
            logger.warning("evaluate JSON 解析失败: %s", e)
            return default
        except Exception as e:
            logger.exception("evaluate 异常: %s", e)
            return default



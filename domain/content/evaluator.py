"""
评估脑：对生成内容多维度打分并给出改进建议。
可单独开发与测试，依赖 ILLMClient 注入。
"""
from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.ai.port import ILLMClient

logger = logging.getLogger(__name__)

DEFAULT_EVALUATION = {
    "scores": {"consistency": 5, "creativity": 5, "safety": 5, "platform_fit": 5},
    "overall": 5.0,
    "suggestions": "评估服务暂时不可用，已使用默认结果，主流程继续。",
    "overall_score": 5,
    "evaluation_failed": True,
}


class ContentEvaluator:
    """评估脑：对推广内容四维度打分并给出改进建议。"""

    def __init__(self, llm_client: "ILLMClient") -> None:
        self._llm = llm_client

    async def evaluate(self, content: str, context: dict[str, Any]) -> dict[str, Any]:
        """
        四维度打分：consistency、creativity、safety、platform_fit。
        返回 scores、overall、suggestions、overall_score。
        """
        default = DEFAULT_EVALUATION.copy()
        brand_name = context.get("brand_name", "")
        topic = context.get("topic", "")
        analysis_summary = context.get("analysis", "")

        system_prompt = (
            "你是一位营销文案评审，对推广内容做多维度打分并给出改进建议。"
            "你必须只输出一个纯 JSON 对象，不要有任何其他文字、说明或 markdown。只输出 JSON。"
        )
        user_prompt = f"""请对以下推广内容从四个维度打分（每项 1-10 分），并给出综合分与简要改进意见。

【待评估内容】
{content[:2000]}

【本次请求 / 分析上下文】
品牌名称：{brand_name}
热点/主题：{topic}
分析摘要：{analysis_summary or "无"}

【四个维度】
1. consistency（与品牌目标的一致性）
2. creativity（创意度）
3. safety（语言风险/合规）
4. platform_fit（平台风格契合度）

【输出格式】只输出一个纯 JSON 对象。固定格式示例：
{{"scores": {{"consistency": 8, "creativity": 9, "safety": 9, "platform_fit": 8}}, "overall": 8.5, "suggestions": "一两句改进建议"}}

- scores：必须包含 consistency、creativity、safety、platform_fit，均为整数 1-10
- overall：综合分，数字
- suggestions：字符串，简要改进意见

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

            return {
                "scores": {
                    "consistency": scores.get("consistency", 0),
                    "creativity": scores.get("creativity", 0),
                    "safety": scores.get("safety", 0),
                    "platform_fit": scores.get("platform_fit", 0),
                },
                "overall": round(overall, 1),
                "suggestions": data.get("suggestions", "") or default["suggestions"],
                "overall_score": overall_score,
            }
        except json.JSONDecodeError as e:
            logger.warning("evaluate JSON 解析失败: %s", e)
            return default
        except Exception as e:
            logger.exception("evaluate 异常: %s", e)
            return default



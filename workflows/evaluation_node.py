"""
评估节点：对生成内容与分析结果进行多维度评估，并标记是否需要修订。
通过 create_evaluation_node(ai_service) 注入与工作流一致的 AI 服务实例（含缓存/配置）。
"""
import json
import logging
import time
from typing import Any

from services.ai_service import SimpleAIService

logger = logging.getLogger(__name__)

# 评估失败时的默认结构：各维度 5 分、总分 5，并标记 evaluation_failed，便于下游识别
DEFAULT_EVALUATION = {
    "scores": {"consistency": 5, "creativity": 5, "safety": 5, "platform_fit": 5},
    "overall": 5.0,
    "suggestions": "评估服务暂时不可用，已使用默认结果，主流程继续。",
    "overall_score": 5,
    "evaluation_failed": True,
}


def create_evaluation_node(ai_service: SimpleAIService):
    """
    返回使用指定 ai_service 的评估节点函数，供 create_workflow 注入与 analyze/generate 一致的实例。
    """
    async def evaluation_node(state: dict) -> dict:
        t0 = time.perf_counter()
        try:
            content = state.get("content") or ""
            analysis = state.get("analysis")

            context: dict[str, Any] = {"brand_name": "", "topic": "", "analysis": ""}
            try:
                user_input = state.get("user_input") or "{}"
                data = json.loads(user_input) if isinstance(user_input, str) else user_input
                if isinstance(data, dict):
                    context["brand_name"] = data.get("brand_name") or ""
                    context["topic"] = data.get("topic") or ""
            except (json.JSONDecodeError, TypeError):
                pass

            if isinstance(analysis, dict):
                context["analysis"] = (
                    f"得分 {analysis.get('semantic_score', 0)}；"
                    f"切入点：{analysis.get('angle', '')}；理由：{analysis.get('reason', '')}"
                )
            else:
                context["analysis"] = analysis if isinstance(analysis, str) else ""

            try:
                evaluation_result = await ai_service.evaluate_content(content, context)
            except Exception as e:
                logger.warning("evaluate_content 调用失败，使用默认评估: %s", e, exc_info=True)
                evaluation_result = DEFAULT_EVALUATION.copy()

            if not isinstance(evaluation_result, dict):
                evaluation_result = DEFAULT_EVALUATION.copy()

            if evaluation_result.get("evaluation_failed") is True:
                need_revision = False
            else:
                overall_score = evaluation_result.get("overall_score", 0)
                if isinstance(overall_score, (int, float)):
                    overall_score = int(overall_score)
                else:
                    overall_score = 0
                need_revision = overall_score < 6

            duration = round(time.perf_counter() - t0, 4)
            return {
                **state,
                "evaluation": evaluation_result,
                "need_revision": need_revision,
                "stage_durations": {**state.get("stage_durations", {}), "evaluate": duration},
                "analyze_cache_hit": state.get("analyze_cache_hit", False),
                "used_tags": state.get("used_tags", []),
            }
        except Exception as e:
            logger.exception("evaluation_node 发生未预期异常，返回默认评估以保证工作流继续: %s", e)
            duration = round(time.perf_counter() - t0, 4)
            return {
                **(state if isinstance(state, dict) else {}),
                "evaluation": DEFAULT_EVALUATION.copy(),
                "need_revision": False,
                "stage_durations": {**(state.get("stage_durations", {}) if isinstance(state, dict) else {}), "evaluate": duration},
                "analyze_cache_hit": state.get("analyze_cache_hit", False) if isinstance(state, dict) else False,
                "used_tags": state.get("used_tags", []) if isinstance(state, dict) else [],
            }
    return evaluation_node

"""
固定 Plan：内容矩阵。意图/话题匹配时自动选用。
"""
from __future__ import annotations

from plans.registry import PLAN_TYPE_FIXED, register

TEMPLATE_CONTENT_MATRIX = "content_matrix"


def _intent_selector(intent: str, ip_context: dict) -> bool:
    topic = (ip_context.get("topic") or "").lower()
    if "内容" in intent:
        return True
    if "矩阵" in topic or "选题" in topic:
        return True
    return False


def register_plan() -> None:
    register(
        TEMPLATE_CONTENT_MATRIX,
        name="内容矩阵",
        plan_type=PLAN_TYPE_FIXED,
        steps=[
            {"step": "memory_query", "plugins": [], "params": {}, "reason": "用户偏好"},
            {"step": "analyze", "plugins": ["content_direction_ranking", "topic_selection_plugin"], "params": {}, "reason": "内容方向与选题"},
            {"step": "analyze", "plugins": ["industry_news_bilibili_rankings"], "params": {}, "reason": "行业与热点"},
            {"step": "generate", "plugins": ["text_generator"], "params": {"platform": ""}, "reason": "生成内容"},
            {"step": "evaluate", "plugins": [], "params": {}, "reason": "评估"},
        ],
        description="内容矩阵：偏好→方向与选题→热点→生成→评估",
        intent_selector=_intent_selector,
        selector_priority=30,
    )


register_plan()

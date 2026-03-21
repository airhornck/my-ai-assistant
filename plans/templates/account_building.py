"""
固定 Plan：账号打造。意图/话题匹配时自动选用。
"""
from __future__ import annotations

from plans.registry import PLAN_TYPE_FIXED, register

TEMPLATE_ACCOUNT_BUILDING = "account_building"


def _intent_selector(intent: str, ip_context: dict) -> bool:
    topic = (ip_context.get("topic") or "").lower()
    if "打造" in intent or "ip" in intent:
        return True
    if "账号" in topic:
        return True
    return False


def register_plan() -> None:
    register(
        TEMPLATE_ACCOUNT_BUILDING,
        name="账号打造",
        plan_type=PLAN_TYPE_FIXED,
        steps=[
            {"step": "memory_query", "plugins": [], "params": {}, "reason": "查询用户历史偏好"},
            {"step": "analyze", "plugins": ["business_positioning_plugin", "content_positioning_plugin"], "params": {}, "reason": "定位与内容方向"},
            {"step": "analyze", "plugins": ["topic_selection_plugin"], "params": {}, "reason": "选题与内容支柱"},
            {"step": "generate", "plugins": ["text_generator"], "params": {"platform": ""}, "reason": "生成示例内容"},
            {"step": "evaluate", "plugins": [], "params": {}, "reason": "评估与建议"},
        ],
        description="账号打造：偏好→定位→选题→生成→评估",
        intent_selector=_intent_selector,
        selector_priority=20,
    )


register_plan()

"""
固定 Plan：能力接口 - 内容方向榜单。由能力 API 按 template_id 直接引用。
"""
from __future__ import annotations

from plans.registry import PLAN_TYPE_FIXED, register

CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING = "capability_content_direction_ranking"


def register_plan() -> None:
    register(
        CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING,
        name="内容方向榜单",
        plan_type=PLAN_TYPE_FIXED,
        steps=[
            {"step": "memory_query", "plugins": [], "params": {}, "reason": "查询用户偏好与画像"},
            {"step": "analyze", "plugins": ["content_direction_ranking"], "params": {}, "reason": "内容方向榜单"},
        ],
        description="能力接口：内容方向榜单",
    )


register_plan()

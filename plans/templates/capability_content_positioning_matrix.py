"""
固定 Plan：能力接口 - 内容定位矩阵。由能力 API 按 template_id 直接引用。
"""
from __future__ import annotations

from plans.registry import PLAN_TYPE_FIXED, register

CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX = "capability_content_positioning_matrix"


def register_plan() -> None:
    register(
        CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX,
        name="内容定位矩阵",
        plan_type=PLAN_TYPE_FIXED,
        steps=[
            {"step": "memory_query", "plugins": [], "params": {}, "reason": "查询用户偏好与画像"},
            {"step": "analyze", "plugins": ["content_positioning"], "params": {}, "reason": "内容定位矩阵与人设"},
        ],
        description="能力接口：内容定位矩阵",
    )


register_plan()

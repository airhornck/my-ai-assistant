"""
固定 Plan：能力接口 - 案例库列表。由能力 API 按 template_id 直接引用。
"""
from __future__ import annotations

from plans.registry import PLAN_TYPE_FIXED, register

CAPABILITY_TEMPLATE_CASE_LIBRARY = "capability_case_library"


def register_plan() -> None:
    register(
        CAPABILITY_TEMPLATE_CASE_LIBRARY,
        name="案例库列表",
        plan_type=PLAN_TYPE_FIXED,
        steps=[
            {"step": "memory_query", "plugins": [], "params": {}, "reason": "查询用户偏好与行业"},
            {"step": "case_library", "plugins": [], "params": {"page": 1, "page_size": 20}, "reason": "定位决策案例库列表"},
        ],
        description="能力接口：案例库列表",
    )


register_plan()

"""
固定 Plan：能力接口 - 每周决策快照。由能力 API 按 template_id 直接引用。
"""
from __future__ import annotations

from plans.registry import PLAN_TYPE_FIXED, register

CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT = "capability_weekly_decision_snapshot"


def register_plan() -> None:
    register(
        CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT,
        name="每周决策快照",
        plan_type=PLAN_TYPE_FIXED,
        steps=[
            {"step": "memory_query", "plugins": [], "params": {}, "reason": "查询用户偏好与画像"},
            {"step": "analyze", "plugins": ["account_diagnosis"], "params": {}, "reason": "账号诊断"},
            {"step": "analyze", "plugins": ["content_positioning"], "params": {}, "reason": "内容定位"},
            {"step": "analyze", "plugins": ["weekly_decision_snapshot"], "params": {}, "reason": "每周决策快照"},
        ],
        description="能力接口：每周决策快照",
    )


register_plan()

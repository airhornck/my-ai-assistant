"""
固定 Plan：IP/账号诊断。意图匹配时自动选用。
"""
from __future__ import annotations

from plans.registry import PLAN_TYPE_FIXED, register

TEMPLATE_IP_DIAGNOSIS = "ip_diagnosis"


def _intent_selector(intent: str, ip_context: dict) -> bool:
    topic = (ip_context.get("topic") or "").lower()
    if intent == "account_diagnosis":
        return True
    if "诊断" in intent:
        return True
    if "账号" in intent and ("流量" in topic or "数据" in topic):
        return True
    return False


def register_plan() -> None:
    register(
        TEMPLATE_IP_DIAGNOSIS,
        name="IP/账号诊断",
        plan_type=PLAN_TYPE_FIXED,
        steps=[
            {"step": "analyze", "plugins": ["account_diagnosis_plugin"], "params": {}, "reason": "账号诊断分析"},
            {"step": "casual_reply", "plugins": [], "params": {"message": ""}, "reason": "输出诊断报告"},
        ],
        description="IP/账号诊断：分析 + 输出诊断报告",
        intent_selector=_intent_selector,
        selector_priority=10,
    )


register_plan()

"""
Plan 模块：模板注册、解析、Intake 配置与模板 ID 常量统一入口。

使用方式：
- 获取步骤：get_plan(template_id) 或 get_fixed_plan(template_id)
- 解析模板 ID：resolve_template_id(intent, ip_context)
- 列表/元数据：list_template_ids(), get_template_meta(template_id)（含 name、description 等）
- Intake 必填/可选字段：IP_INTAKE_REQUIRED_KEYS, IP_INTAKE_OPTIONAL_KEYS
- 模板 ID 常量：TEMPLATE_IP_DIAGNOSIS, CAPABILITY_TEMPLATE_* 等
"""
from __future__ import annotations

# 触发内置模板注册
import plans.templates  # noqa: F401

from plans.registry import (
    PLAN_TEMPLATE_DYNAMIC,
    PLAN_TYPE_DYNAMIC,
    PLAN_TYPE_FIXED,
    apply_clear_template_lock_to_ip_context,
    clear_template_lock_requested,
    get_plan,
    get_template_meta,
    list_template_ids,
    register,
    resolve_template_id,
)
from plans.intake import (
    IP_INTAKE_OPTIONAL_KEYS,
    IP_INTAKE_REQUIRED_KEYS,
)
from plans.templates import (
    CAPABILITY_TEMPLATE_CASE_LIBRARY,
    CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING,
    CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX,
    CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT,
    TEMPLATE_ACCOUNT_BUILDING,
    TEMPLATE_CONTENT_MATRIX,
    TEMPLATE_IP_DIAGNOSIS,
)


def get_fixed_plan(template_id: str) -> list[dict] | None:
    """按模板 ID 获取固定 Plan 步骤列表（深拷贝）。兼容旧名，等价于 get_plan(template_id)。"""
    return get_plan(template_id)


__all__ = [
    "PLAN_TEMPLATE_DYNAMIC",
    "PLAN_TYPE_FIXED",
    "PLAN_TYPE_DYNAMIC",
    "apply_clear_template_lock_to_ip_context",
    "clear_template_lock_requested",
    "IP_INTAKE_REQUIRED_KEYS",
    "IP_INTAKE_OPTIONAL_KEYS",
    "TEMPLATE_IP_DIAGNOSIS",
    "TEMPLATE_ACCOUNT_BUILDING",
    "TEMPLATE_CONTENT_MATRIX",
    "CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING",
    "CAPABILITY_TEMPLATE_CASE_LIBRARY",
    "CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX",
    "CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT",
    "get_plan",
    "get_fixed_plan",
    "get_template_meta",
    "list_template_ids",
    "register",
    "resolve_template_id",
]

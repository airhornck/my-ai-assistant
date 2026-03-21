"""
IP 打造 Intake 阶段：必填/可选字段定义，用于引导收集与 pending_questions。
数据源统一为 intake_guide，此处仅复用以保持现有引用不破坏。
"""
from __future__ import annotations

from intake_guide import (
    IP_INTAKE_OPTIONAL_KEYS,
    IP_INTAKE_REQUIRED_KEYS,
)

__all__ = ["IP_INTAKE_REQUIRED_KEYS", "IP_INTAKE_OPTIONAL_KEYS"]

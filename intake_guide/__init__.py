"""
用户友好引导模块

实现：
- 每轮只问 1～3 个关键问题
- 选项化 + 可跳过
- 实时回显已收集信息
- ip_context 持久化，支持多轮累积
- 可作为独立 Intake 组件，前端可用进度条或状态提示展示

流程：用户输入 → IntentAgent → 字段抽取 → ip_context 更新
    → 缺失字段? → 生成 pending_questions → 前端显示问题
    → 用户回答 → 更新 ip_context → 下一轮
"""
from __future__ import annotations

from intake_guide.config import (
    IP_INTAKE_OPTIONAL_KEYS,
    IP_INTAKE_REQUIRED_KEYS,
    OPTIONAL_KEYS,
    REQUIRED_KEYS,
)
from intake_guide.echo import format_echo
from intake_guide.infer import infer_fields
from intake_guide.merge import merge_context
from intake_guide.questions import build_pending_questions, missing_required

__all__ = [
    "REQUIRED_KEYS",
    "OPTIONAL_KEYS",
    "IP_INTAKE_REQUIRED_KEYS",
    "IP_INTAKE_OPTIONAL_KEYS",
    "infer_fields",
    "merge_context",
    "missing_required",
    "build_pending_questions",
    "format_echo",
]

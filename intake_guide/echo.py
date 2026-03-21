"""
用户友好引导：实时回显已收集信息，供前端进度条/状态展示。
"""
from __future__ import annotations

from typing import Any

# 字段 key → 前端展示标签（简短）
LABELS: dict[str, str] = {
    "brand_name": "品牌/账号",
    "topic": "目标/主题",
    "product_desc": "产品描述",
    "platform": "平台",
}


def format_echo(ip_context: dict | None) -> str:
    """
    将已收集的 ip_context 格式化为「已收集信息」回显文案。
    可作为独立 Intake 组件的一部分，前端用进度条或状态提示展示。
    """
    ctx = ip_context or {}
    parts = []
    for k, label in LABELS.items():
        v = ctx.get(k)
        if v is not None and str(v).strip():
            parts.append(f"{label}：{str(v).strip()}")
    if not parts:
        return "（尚未填写，请按下方问题补充）"
    return "；".join(parts)

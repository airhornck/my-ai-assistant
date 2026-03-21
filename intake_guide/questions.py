"""
用户友好引导：每轮 1～3 个关键问题、选项化、可跳过。
"""
from __future__ import annotations

from typing import Any

from intake_guide.config import OPTIONAL_KEYS, REQUIRED_KEYS

# 字段 key → 问题文案 + 选项 + 是否可跳过（产品化：选项化 + 可跳过）
QUESTION_MAP: dict[str, dict[str, Any]] = {
    "brand_name": {
        "key": "brand_name",
        "question": "请简单介绍一下您的品牌或账号名称？",
        "options": ["暂未命名/暂无账号"],
        "optional": False,
    },
    "topic": {
        "key": "topic",
        "question": "您这次主要想达成什么目标？",
        "options": ["做小红书", "做抖音", "做B站", "提升曝光", "打造个人IP", "产品推广", "其他"],
        "optional": False,
    },
    "product_desc": {
        "key": "product_desc",
        "question": "产品/服务简要描述？（可跳过）",
        "options": [],
        "optional": True,
    },
    "platform": {
        "key": "platform",
        "question": "主要运营平台是？",
        "options": ["B站", "小红书", "抖音", "视频号", "多平台"],
        "optional": False,
    },
}


def missing_required(ip_context: dict | None) -> list[str]:
    """返回尚未填写的必填字段名。"""
    ctx = ip_context or {}
    return [k for k in REQUIRED_KEYS if not (ctx.get(k) or "").strip()]


def build_pending_questions(
    missing: list[str],
    intent: str = "",
    max_questions: int = 3,
) -> list[dict[str, Any]]:
    """
    根据缺失字段生成 1～max_questions 个友好问题（选项化 + 可跳过）。
    满足：每轮只问 1～3 个关键问题、选项化、可跳过。
    """
    out = []
    for k in missing[:max_questions]:
        entry = QUESTION_MAP.get(k)
        if entry:
            out.append(dict(entry))
    if not out and missing:
        for k in missing[:max_questions]:
            out.append({
                "key": k,
                "question": f"请补充：{k}",
                "options": [],
                "optional": k in OPTIONAL_KEYS,
            })
    return out

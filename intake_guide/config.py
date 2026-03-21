"""
用户友好引导：必填/可选字段配置。
作为独立模块的单一数据源，plans.intake 可从此处复用以保持引用一致。
"""
from __future__ import annotations

# 必填字段满足后即可从 intake 进入 plan 阶段（可按业务调整）
REQUIRED_KEYS = [
    "brand_name",   # 品牌/账号名
    "topic",        # 目标/主题（如「做小红书」「提升曝光」）
]

# 可选字段，有则增强效果；引导时可标 optional=True 支持跳过
OPTIONAL_KEYS = [
    "product_desc",
    "target_audience",
    "platform",
    "goal",
    "style",
    "differentiator",
    "resources",
    "constraints",
]

# 供 plans 兼容的别名
IP_INTAKE_REQUIRED_KEYS = REQUIRED_KEYS
IP_INTAKE_OPTIONAL_KEYS = OPTIONAL_KEYS

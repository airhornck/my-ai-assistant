"""
多模态工厂：按环境变量选择 Mock 或阿里云实现。
"""
from __future__ import annotations

import os

from core.multimodal.port import IMultimodalPort
from core.multimodal.mock_adapter import MockMultimodalAdapter
from core.multimodal.aliyun_adapter import AliyunMultimodalAdapter


def get_multimodal_port(
    *,
    provider: str | None = None,
    api_key: str | None = None,
) -> IMultimodalPort:
    """
    获取多模态 Port。
    环境变量：MULTIMODAL_PROVIDER=mock|aliyun
    未配置或 mock 时返回 Mock 实现；aliyun 时返回阿里云实现（当前为占位）。
    """
    p = (provider or os.getenv("MULTIMODAL_PROVIDER", "mock")).strip().lower()
    if p == "aliyun":
        return AliyunMultimodalAdapter(api_key=api_key)
    return MockMultimodalAdapter()

"""
预测模型工厂：按环境变量选择实现。
"""
from __future__ import annotations

import os

from services.prediction.port import IPredictionPort
from services.prediction.mock_adapter import MockPredictionAdapter


def get_prediction_port(
    *,
    provider: str | None = None,
) -> IPredictionPort:
    """
    获取预测 Port。
    环境变量：PREDICTION_PROVIDER=mock|local|api
    当前仅 mock 可用；local/api 为占位，后续接入。
    """
    p = (provider or os.getenv("PREDICTION_PROVIDER", "mock")).strip().lower()
    if p in ("local", "api"):
        # TODO: 接入本地模型或第三方 API
        pass
    return MockPredictionAdapter()

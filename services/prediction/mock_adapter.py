"""
预测模型 Mock 适配器：开发/测试用。
"""
from __future__ import annotations

import logging
from typing import Any

from services.prediction.port import IPredictionPort, ViralPredictionResult, CTRPredictionResult

logger = logging.getLogger(__name__)


class MockPredictionAdapter(IPredictionPort):
    """Mock 实现：返回固定分数。"""

    async def predict_viral(
        self,
        features: dict[str, Any],
        *,
        platform: str = "",
    ) -> ViralPredictionResult:
        logger.debug("Mock 预测: predict_viral(platform=%s)", platform)
        return ViralPredictionResult(
            score=0.65,
            confidence=0.5,
            factors={"hook": 0.25, "trend": 0.2, "structure": 0.2},
            raw={"source": "mock"},
        )

    async def predict_ctr(
        self,
        cover_features: dict[str, Any],
        title: str = "",
        *,
        platform: str = "",
    ) -> CTRPredictionResult:
        logger.debug("Mock 预测: predict_ctr(platform=%s)", platform)
        return CTRPredictionResult(
            ctr=0.03,
            confidence=0.5,
            factors={"cover": 0.3, "title": 0.2},
            raw={"source": "mock"},
        )

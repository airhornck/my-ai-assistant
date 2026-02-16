"""
预测模型 Port：爆款预测、CTR 预估等接口抽象。
实现者可替换为本地模型、第三方 API。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ViralPredictionResult:
    """爆款预测结果。"""

    score: float  # 0~1，爆款概率
    confidence: float  # 模型置信度
    factors: dict[str, float]  # 各因子贡献，如 {"hook": 0.3, "trend": 0.2}
    raw: dict[str, Any] | None = None


@dataclass
class CTRPredictionResult:
    """CTR 预估结果。"""

    ctr: float  # 点击率，如 0.05 表示 5%
    confidence: float
    factors: dict[str, float]
    raw: dict[str, Any] | None = None


class IPredictionPort(ABC):
    """预测模型端口。"""

    @abstractmethod
    async def predict_viral(
        self,
        features: dict[str, Any],
        *,
        platform: str = "",
    ) -> ViralPredictionResult:
        """
        爆款预测。
        :param features: 内容特征（如来自结构化拆解、多模态分析）
        :param platform: 平台标识
        :return: 预测结果
        """
        ...

    @abstractmethod
    async def predict_ctr(
        self,
        cover_features: dict[str, Any],
        title: str = "",
        *,
        platform: str = "",
    ) -> CTRPredictionResult:
        """
        CTR 预估。
        :param cover_features: 封面特征（来自多模态分析）
        :param title: 标题
        :param platform: 平台
        :return: 预估结果
        """
        ...

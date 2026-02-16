"""
样本库 Port：爆款样本入库与检索。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SampleRecord:
    """单条样本记录。"""

    video_id: str
    platform: str
    title: str = ""
    # 多模态/拆解特征（向量或结构化）
    features: dict[str, Any] = field(default_factory=dict)
    # 基础指标（供训练/筛选）
    metrics: dict[str, float] = field(default_factory=dict)  # 如 play_count, ctr, like_rate
    # 元数据
    published_at: str = ""  # ISO 日期
    category: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "platform": self.platform,
            "title": self.title,
            "features": self.features,
            "metrics": self.metrics,
            "published_at": self.published_at,
            "category": self.category,
            "extra": self.extra,
        }


class SampleLibraryPort(ABC):
    """样本库端口。"""

    @abstractmethod
    async def ingest(
        self,
        samples: list[SampleRecord | dict],
        *,
        batch_size: int = 100,
    ) -> int:
        """
        批量入库。
        :param samples: 样本列表
        :param batch_size: 每批大小
        :return: 成功入库数量
        """
        ...

    @abstractmethod
    async def search(
        self,
        *,
        platform: str = "",
        category: str = "",
        top_k: int = 20,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[SampleRecord]:
        """
        按条件检索样本。
        """
        ...

    @abstractmethod
    async def get_by_id(
        self,
        video_id: str,
        platform: str = "",
    ) -> Optional[SampleRecord]:
        """按 ID 查询单条。"""
        ...

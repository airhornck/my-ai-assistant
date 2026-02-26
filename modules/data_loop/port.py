"""
数据闭环 Port：反馈事件与平台回流数据接口抽象。
实现者可替换为不同存储后端。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FeedbackEvent:
    """用户反馈事件。"""

    id: str
    user_id: str
    session_id: str = ""
    event_type: str = ""  # user_submit, system_auto
    content: str = ""
    created_at: str = ""


@dataclass
class PlatformMetric:
    """平台回流指标。"""

    id: str
    video_id: str
    platform: str = ""
    exposure: int = 0
    click: int = 0
    conversion: int = 0
    ctr: float = 0.0
    recorded_at: str = ""


class IDataLoopPort(ABC):
    """数据闭环端口。"""

    @abstractmethod
    async def record_feedback(
        self,
        user_id: str,
        session_id: str = "",
        event_type: str = "user_submit",
        content: str = "",
        **kwargs: Any,
    ) -> FeedbackEvent:
        """
        记录用户反馈。
        """
        ...

    @abstractmethod
    async def get_feedbacks(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[FeedbackEvent]:
        """
        查询反馈记录。
        """
        ...

    @abstractmethod
    async def record_platform_metric(
        self,
        video_id: str,
        platform: str,
        exposure: int = 0,
        click: int = 0,
        conversion: int = 0,
        **kwargs: Any,
    ) -> PlatformMetric:
        """
        记录平台回流指标。
        """
        ...

    @abstractmethod
    async def get_platform_metrics(
        self,
        video_id: str | None = None,
        platform: str | None = None,
        limit: int = 100,
    ) -> list[PlatformMetric]:
        """
        查询平台指标。
        """
        ...

    @abstractmethod
    async def get_video_performance(
        self,
        video_id: str,
    ) -> dict[str, Any]:
        """
        获取视频综合表现（聚合指标）。
        """
        ...

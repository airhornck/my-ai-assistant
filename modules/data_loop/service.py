"""
数据闭环服务：写入反馈事件与平台回流指标，供案例打分与统计使用。
写入采用单条/批量接口，避免阻塞主链路；索引由表结构保证。
"""
from __future__ import annotations

import logging
from typing import Any, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import FeedbackEvent, PlatformMetric

logger = logging.getLogger(__name__)

SOURCE_USER_SUBMIT = "user_submit"
SOURCE_PLATFORM_REFLOW = "platform_reflow"
METRIC_EXPOSURE = "exposure"
METRIC_CLICK = "click"
METRIC_CONVERSION = "conversion"


class DataLoopService:
    """接收用户反馈与平台回流，写入 feedback_events / platform_metrics。"""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def record_feedback(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
        rating: int | None = None,
        comment: str | None = None,
        payload: dict | None = None,
    ) -> int | None:
        """写入一条用户反馈事件。返回 id，失败返回 None。"""
        async with self._session_factory() as session:
            try:
                ev = FeedbackEvent(
                    session_id=session_id,
                    user_id=user_id,
                    source=SOURCE_USER_SUBMIT,
                    rating_or_metric=rating,
                    payload=payload if payload is not None else ({"comment": comment} if comment else None),
                )
                session.add(ev)
                await session.commit()
                await session.refresh(ev)
                return ev.id
            except Exception as e:
                logger.warning("record_feedback 失败: %s", e)
                await session.rollback()
                return None

    async def record_platform_metrics(
        self,
        items: List[dict],
    ) -> int:
        """
        批量写入平台回流指标。items 每项需含 metric_type，可选 session_id, user_id, value, dimensions。
        返回成功写入条数。
        """
        if not items:
            return 0
        async with self._session_factory() as session:
            try:
                for it in items:
                    m = PlatformMetric(
                        session_id=it.get("session_id"),
                        user_id=it.get("user_id"),
                        metric_type=it.get("metric_type", "unknown"),
                        value=it.get("value"),
                        dimensions=it.get("dimensions"),
                    )
                    session.add(m)
                await session.commit()
                return len(items)
            except Exception as e:
                logger.warning("record_platform_metrics 失败: %s", e)
                await session.rollback()
                return 0

    async def get_feedback_by_session(self, session_id: str, limit: int = 10) -> List[dict]:
        """按 session_id 查询最近反馈事件，用于与交互/案例关联。"""
        async with self._session_factory() as session:
            r = await session.execute(
                select(FeedbackEvent)
                .where(FeedbackEvent.session_id == session_id)
                .order_by(FeedbackEvent.created_at.desc())
                .limit(limit)
            )
            rows = r.scalars().all()
            return [
                {
                    "id": x.id,
                    "source": x.source,
                    "rating_or_metric": x.rating_or_metric,
                    "payload": x.payload,
                    "created_at": x.created_at.isoformat() if x.created_at else None,
                }
                for x in rows
            ]

"""
反馈服务：处理用户对生成内容的显式反馈，更新 InteractionHistory 并触发画像优化。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import InteractionHistory

logger = logging.getLogger(__name__)

QUEUE_PROFILE_OPT = "queue:profile_opt"


class FeedbackService:
    """
    依赖数据库会话（通过会话工厂获取）与 Redis 客户端。
    负责记录反馈、并在高质量反馈时触发 MemoryOptimizer 优先处理。
    """

    def __init__(
        self,
        session_factory: Any,
        redis_client: Any,
    ) -> None:
        """
        Args:
            session_factory: 异步会话工厂（如 AsyncSessionLocal），调用后得到 AsyncSession。
            redis_client: Redis 异步客户端，用于 trigger_optimization 入队。
        """
        self._session_factory = session_factory
        self._redis = redis_client

    async def record(
        self,
        session_id: str,
        rating: int,
        comment: str,
    ) -> None:
        """
        根据 session_id 找到对应的 InteractionHistory 记录（取该会话最新一条），
        更新其 user_rating 和 user_comment。
        若 rating >= 4，则调用 trigger_optimization(user_id) 供后台优先处理。
        """
        async with self._session_factory() as session:
            r = await session.execute(
                select(InteractionHistory)
                .where(InteractionHistory.session_id == session_id)
                .order_by(InteractionHistory.created_at.desc())
                .limit(1)
            )
            row = r.scalar_one_or_none()
            if row is None:
                logger.warning("record: 未找到 session_id=%s 的 InteractionHistory", session_id)
                return
            row.user_rating = rating
            row.user_comment = comment or None
            await session.commit()
            user_id = row.user_id
        if rating >= 4:
            await self.trigger_optimization(user_id)

    async def trigger_optimization(self, user_id: str) -> None:
        """
        将 user_id 放入 Redis 队列，供后台 MemoryOptimizer 优先处理该用户的历史数据。
        当收到高质量反馈（如 rating >= 4）时由 record 调用。
        """
        await self._redis.lpush(QUEUE_PROFILE_OPT, user_id)
        logger.info("trigger_optimization: user_id=%s 已入队", user_id)

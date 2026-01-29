"""
记忆优化服务：独立后台，基于近 24 小时交互历史更新用户画像标签。
使用独立数据库连接池，可脚本方式运行；主循环每 6 小时执行一次优化。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import redis.asyncio as redis
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import InteractionHistory, UserProfile

logger = logging.getLogger(__name__)

# 至少几条交互记录才参与画像优化
MIN_RECORDS_FOR_OPTIMIZATION = 2
# 主循环间隔（秒），6 小时
CYCLE_INTERVAL_SECONDS = 6 * 3600  # 21600


def _convert_to_async_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    raise ValueError(f"不支持的数据库URL格式: {database_url}")


class MemoryOptimizer:
    """
    独立记忆优化服务：使用自己的 AsyncEngine/连接池，不共用主 API 的 engine。
    每 6 小时执行一次优化周期，根据近 24 小时交互历史更新 UserProfile.tags。
    """

    def __init__(
        self,
        database_url: str,
        ai_service: Optional[Any] = None,
        redis_url: Optional[str] = None,
    ) -> None:
        """
        Args:
            database_url: 数据库连接串（如 postgresql://user:pass@host/db），会转为 asyncpg。
            ai_service: 可选，若提供且带 derive_user_tags 则用之；否则内部用 DeepSeek（与主应用一致）做分析。
            redis_url: 可选，若提供则检查 user_tags_explicit:{user_id}，存在则跳过该用户，避免覆盖用户显式写入的标签。
        """
        self._database_url = database_url
        self._ai_service = ai_service
        self._redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        self._llm: Optional[ChatOpenAI] = None

        async_url = _convert_to_async_url(database_url)
        self._engine = create_async_engine(
            async_url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=2,
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    async def _get_redis(self) -> Optional[redis.Redis]:
        """懒加载 Redis 客户端（仅当配置了 redis_url 时）。"""
        if self._redis_url is None:
            return None
        if self._redis is None:
            self._redis = redis.Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def _get_llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model="deepseek-chat",
                base_url="https://api.deepseek.com",
                api_key=os.getenv("DEEPSEEK_API_KEY", "sk-cef65d7e728d43d79a4a23d642faa6d0"),
                temperature=0.3,
            )
        return self._llm

    async def _analyze_user_pattern(self, summary: str) -> list[str]:
        """
        根据用户近期交互摘要，调用 AI 分析核心关注领域、内容偏好风格和兴趣标签。
        返回 3–5 个标签字符串；解析失败返回空列表。
        """
        if not summary.strip():
            return []
        if self._ai_service is not None and hasattr(self._ai_service, "derive_user_tags"):
            return await self._ai_service.derive_user_tags([summary])

        system_prompt = (
            "你是一名用户洞察专家。根据用户近期与推广内容的交互摘要，"
            "提炼出 3–5 个简短的关键词或兴趣标签（如「科技数码」「偏爱简洁文案」「关注促销」）。"
            "只输出一个 JSON 数组，不要有任何其他文字。"
        )
        user_prompt = f"""【用户近期交互摘要】
{summary[:3000]}

请只输出一个 JSON 数组，例如：["科技数码", "偏爱简洁文案", "关注促销"]
不要有任何其他文字、标点或说明。只输出 JSON。"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        llm = self._get_llm()
        response = await llm.ainvoke(messages)
        raw = (response.content or "").strip()
        for prefix in ("```json", "```"):
            if raw.startswith(prefix):
                raw = raw[len(prefix) :].strip()
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")].strip()
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("_analyze_user_pattern JSON 解析失败: %s\nraw=%s", e, raw[:300])
            return []
        if not isinstance(arr, list):
            return []
        return [str(x).strip() for x in arr if x][:5]

    async def run_optimization_cycle(self) -> None:
        """
        执行一轮优化：查询近 24 小时 InteractionHistory，按 user_id 分组；
        对交互较多的用户做 AI 分析，将得到的标签写入 UserProfile.tags。
        整个周期包在 try/except 中，单次失败只记日志，不导致服务退出。
        """
        try:
            logger.info("记忆优化周期开始")
            now = datetime.now(timezone.utc)
            since = now - timedelta(hours=24)

            async with self._session_factory() as session:
                r = await session.execute(
                    select(InteractionHistory)
                    .where(InteractionHistory.created_at >= since)
                    .order_by(InteractionHistory.user_id, InteractionHistory.created_at.desc())
                )
                rows = r.scalars().all()

            by_user: dict[str, list[Any]] = {}
            for row in rows:
                by_user.setdefault(row.user_id, []).append(row)

            updated = 0
            redis_client = await self._get_redis()
            for user_id, records in by_user.items():
                if len(records) < MIN_RECORDS_FOR_OPTIMIZATION:
                    continue
                if redis_client is not None:
                    try:
                        if await redis_client.get("user_tags_explicit:" + user_id):
                            logger.debug("user_id=%s 有用户显式标签，跳过 optimizer 覆盖", user_id)
                            continue
                    except Exception as e:
                        logger.warning("检查 user_tags_explicit 失败 user_id=%s: %s", user_id, e)
                parts = []
                for i, h in enumerate(records[:10], 1):
                    topic = ""
                    if h.user_input:
                        try:
                            data = json.loads(h.user_input)
                            topic = (data.get("topic") or "") if isinstance(data, dict) else ""
                        except (json.JSONDecodeError, TypeError):
                            pass
                    out = (h.ai_output or "")[:200]
                    parts.append(f"[{i}] topic: {topic}; output: {out}")
                summary = "\n".join(parts)

                try:
                    tags = await self._analyze_user_pattern(summary)
                except Exception as e:
                    logger.warning("user_id=%s _analyze_user_pattern 失败: %s", user_id, e, exc_info=True)
                    continue

                if not tags:
                    continue

                async with self._session_factory() as session:
                    await session.execute(
                        update(UserProfile).where(UserProfile.user_id == user_id).values(tags=tags)
                    )
                    await session.commit()
                updated += 1
                logger.info("user_id=%s 已更新 tags=%s", user_id, tags)

            logger.info("记忆优化周期结束，本轮更新 %s 个用户", updated)
        except Exception as e:
            logger.exception("run_optimization_cycle 失败: %s", e)

    async def start(self) -> None:
        """
        后台主循环：每 6 小时执行一次 run_optimization_cycle；
        单轮异常只记日志，然后继续 sleep，避免服务崩溃。
        """
        logger.info("记忆优化服务已启动，间隔 %s 秒", CYCLE_INTERVAL_SECONDS)
        while True:
            try:
                await self.run_optimization_cycle()
            except Exception as e:
                logger.exception("优化周期异常: %s", e)
            await asyncio.sleep(CYCLE_INTERVAL_SECONDS)

    async def close(self) -> None:
        """关闭自有的数据库连接池与 Redis（若有）。"""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        await self._engine.dispose()
        logger.info("MemoryOptimizer 连接池已关闭")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_assistant")
    redis_url = os.getenv("REDIS_URL")
    optimizer = MemoryOptimizer(database_url, redis_url=redis_url)
    try:
        await optimizer.start()
    finally:
        await optimizer.close()


if __name__ == "__main__":
    asyncio.run(main())

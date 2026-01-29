import os
import uuid
import json
from datetime import datetime
from typing import Optional, Dict, Any

import redis.asyncio as redis


class SessionManager:
    """会话管理器，使用 Redis 异步客户端存储会话数据"""

    def __init__(self) -> None:
        """
        初始化时连接 Redis（异步客户端），地址从环境变量 REDIS_URL 读取。
        
        使用 decode_responses=True 自动解码响应为字符串，无需手动 decode。
        """
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    async def create_session(
        self,
        user_id: str,
        initial_data: Optional[Dict[str, Any]] = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """
        创建新会话，返回唯一的 session_id（异步模式）。

        Args:
            user_id: 用户唯一标识
            initial_data: 初始数据字典（可选）
            ttl_seconds: 会话过期时间（秒），默认 3600（1 小时）

        Returns:
            生成的唯一 session_id
        """
        session_id = str(uuid.uuid4())
        payload = {
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "initial_data": initial_data or {},
        }
        key = f"session:{session_id}"
        # 使用 await 调用异步 Redis 客户端
        await self._redis.setex(
            key,
            ttl_seconds,
            json.dumps(payload, ensure_ascii=False),
        )
        return session_id

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话数据（异步模式）。

        Args:
            session_id: 会话 ID

        Returns:
            会话数据字典；不存在则返回 None
        """
        key = f"session:{session_id}"
        # 使用 await 调用异步 Redis 客户端
        # decode_responses=True 时，返回的是字符串，无需 decode
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def update_session(self, session_id: str, key: str, value: Any) -> None:
        """
        更新会话数据：对指定 key 写入 value，并写回 Redis（异步模式）。

        Args:
            session_id: 会话 ID
            key: 要更新的顶层字段名（如 "user_id"、"initial_data" 等）
            value: 新值（需可 JSON 序列化）

        Raises:
            ValueError: 会话不存在时
        """
        redis_key = f"session:{session_id}"
        # 使用 await 调用异步 Redis 客户端
        raw = await self._redis.get(redis_key)
        if raw is None:
            raise ValueError(f"session not found: {session_id}")
        try:
            # decode_responses=True 时，raw 已经是字符串
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError(f"session data invalid: {session_id}")
        payload[key] = value
        # 使用 await 获取 TTL
        ttl = await self._redis.ttl(redis_key)
        ttl = ttl if ttl > 0 else 3600
        # 使用 await 保存更新后的数据
        await self._redis.setex(
            redis_key,
            ttl,
            json.dumps(payload, ensure_ascii=False),
        )

    @property
    def redis(self):
        """只读属性：返回内部的 Redis 异步客户端。"""
        return self._redis

    async def close(self) -> None:
        """
        关闭 Redis 连接（异步模式）。
        
        在应用关闭时调用，确保资源正确释放。
        """
        await self._redis.aclose()

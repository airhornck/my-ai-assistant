import os
import uuid
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

import redis.asyncio as redis


# Redis 键前缀与 TTL
SESSION_KEY_PREFIX = "session:"
USER_THREADS_KEY_PREFIX = "user:"
USER_THREADS_KEY_SUFFIX = ":threads"
THREAD_SESSIONS_KEY_PREFIX = "thread:"
THREAD_SESSIONS_KEY_SUFFIX = ":sessions"
# 对话链（thread）长期主题，TTL 比单次会话更长
THREAD_TTL_SECONDS = 86400 * 7  # 7 天


class SessionManager:
    """
    会话管理器，使用 Redis 异步客户端存储会话数据。

    概念区分：
    - session_id：单次请求的短期记忆，一次交互对应一个 session。
    - thread_id：多次会话的长期主题，同一对话链（如 /new_chat 前的一段对话）共用一个 thread_id。
    - conversation_threads：同一 user_id 下的多条对话链列表，每条链由 thread_id 标识。
    """

    def __init__(self) -> None:
        """
        初始化时连接 Redis（异步客户端），地址从环境变量 REDIS_URL 读取。

        使用 decode_responses=True 自动解码响应为字符串，无需手动 decode。
        """
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def _user_threads_key(self, user_id: str) -> str:
        return f"{USER_THREADS_KEY_PREFIX}{user_id}{USER_THREADS_KEY_SUFFIX}"

    def _thread_sessions_key(self, thread_id: str) -> str:
        return f"{THREAD_SESSIONS_KEY_PREFIX}{thread_id}{THREAD_SESSIONS_KEY_SUFFIX}"

    async def create_session(
        self,
        user_id: str,
        initial_data: Optional[Dict[str, Any]] = None,
        parent_thread_id: Optional[str] = None,
        ttl_seconds: int = 3600,
    ) -> Dict[str, str]:
        """
        创建新会话，返回 session_id 与 thread_id（异步模式）。

        - 若无 parent_thread_id：创建新的对话链（新 thread_id），并将该会话加入该链。
        - 若有 parent_thread_id：不新建对话链，将新会话关联到该父线程。

        Args:
            user_id: 用户唯一标识
            initial_data: 初始数据字典（可选）
            parent_thread_id: 可选父线程 ID；无则新建对话链，有则归属该链
            ttl_seconds: 会话键过期时间（秒），默认 3600（1 小时）

        Returns:
            {"session_id": str, "thread_id": str}
        """
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        if parent_thread_id is None or not parent_thread_id.strip():
            thread_id = str(uuid.uuid4())
            threads_key = self._user_threads_key(user_id)
            sessions_key = self._thread_sessions_key(thread_id)
            pipe = self._redis.pipeline()
            pipe.lpush(threads_key, thread_id)
            pipe.expire(threads_key, THREAD_TTL_SECONDS)
            pipe.lpush(sessions_key, session_id)
            pipe.expire(sessions_key, THREAD_TTL_SECONDS)
            await pipe.execute()
        else:
            thread_id = parent_thread_id.strip()
            sessions_key = self._thread_sessions_key(thread_id)
            await self._redis.lpush(sessions_key, session_id)
            await self._redis.expire(sessions_key, THREAD_TTL_SECONDS)

        payload = {
            "user_id": user_id,
            "thread_id": thread_id,
            "created_at": now,
            "initial_data": initial_data or {},
        }
        key = f"{SESSION_KEY_PREFIX}{session_id}"
        await self._redis.setex(
            key,
            ttl_seconds,
            json.dumps(payload, ensure_ascii=False),
        )
        return {"session_id": session_id, "thread_id": thread_id}

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话数据（异步模式）。

        Args:
            session_id: 会话 ID

        Returns:
            会话数据字典（含 user_id、thread_id、created_at、initial_data）；不存在则返回 None
        """
        key = f"{SESSION_KEY_PREFIX}{session_id}"
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
        redis_key = f"{SESSION_KEY_PREFIX}{session_id}"
        raw = await self._redis.get(redis_key)
        if raw is None:
            raise ValueError(f"session not found: {session_id}")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError(f"session data invalid: {session_id}")
        payload[key] = value
        ttl = await self._redis.ttl(redis_key)
        ttl = ttl if ttl > 0 else 3600
        await self._redis.setex(
            redis_key,
            ttl,
            json.dumps(payload, ensure_ascii=False),
        )

    async def get_conversation_history(
        self,
        user_id: str,
        thread_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        获取某个对话链或该用户所有链的最近历史（异步模式）。

        - thread_id 指定时：返回该链下最近 limit 条会话（按时间倒序）。
        - thread_id 为 None 时：返回该用户下最近 limit 条会话（跨所有链，按时间倒序）。

        Args:
            user_id: 用户唯一标识
            thread_id: 可选对话链 ID；不传则返回所有链的最近历史
            limit: 最多返回条数，默认 10

        Returns:
            会话列表，每项为会话数据（含 session_id、thread_id、created_at、initial_data 等）
        """
        if thread_id is not None and thread_id.strip():
            session_ids = await self._redis.lrange(
                self._thread_sessions_key(thread_id.strip()), 0, limit - 1
            )
            sessions = []
            for sid in session_ids:
                data = await self.get_session(sid)
                if data is not None and data.get("user_id") == user_id:
                    data["session_id"] = sid
                    sessions.append(data)
            return sessions

        threads_key = self._user_threads_key(user_id)
        max_threads_scan = 50
        thread_ids = await self._redis.lrange(threads_key, 0, max_threads_scan - 1)
        if not thread_ids:
            return []
        collected: List[Dict[str, Any]] = []
        for tid in thread_ids:
            sids = await self._redis.lrange(self._thread_sessions_key(tid), 0, limit - 1)
            for sid in sids:
                data = await self.get_session(sid)
                if data is not None and data.get("user_id") == user_id:
                    data["session_id"] = sid
                    data["thread_id"] = data.get("thread_id") or tid
                    collected.append(data)
        collected.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return collected[:limit]

    @property
    def redis(self) -> redis.Redis:
        """只读属性：返回内部的 Redis 异步客户端。"""
        return self._redis

    async def close(self) -> None:
        """
        关闭 Redis 连接（异步模式）。

        在应用关闭时调用，确保资源正确释放。
        """
        await self._redis.aclose()

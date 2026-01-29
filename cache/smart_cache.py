"""
智能缓存服务：缓存 AI 对相似请求的响应，使用 Redis（redis.asyncio）。
支持「分析缓存」的上下文指纹：用户标签 + 近三次交互主题集合，兼顾命中率与个性化。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Awaitable, Callable, Tuple

import redis.asyncio as redis

logger = logging.getLogger(__name__)


def _normalize_for_key(value: Any) -> str:
    """
    归一化用于缓存键的字符串：None/空 → ""，去除首尾空白，内部连续空白压成单空格。
    避免因客户端传参格式差异（空格、换行）导致同义请求键不同。
    """
    if value is None:
        return ""
    s = str(value).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def generate_cache_key(request_data: dict) -> str:
    """
    将请求内容（如 user_id、topic、product_desc）序列化后 MD5 哈希，生成唯一缓存键。
    使用 json.dumps(..., sort_keys=True) 保证相同请求生成相同键。
    不自动归一化；调用方应对 request_data 做归一化后再传入。
    """
    canonical = json.dumps(request_data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def build_analyze_cache_key(
    user_id: str,
    brand_name: str,
    product_desc: str,
    topic: str,
    context_fingerprint: dict | None = None,
) -> str:
    """
    生成分析缓存的 Redis 键：请求四元组归一化 + 上下文指纹（仅用户标签参与键）。
    - 归一化：避免空格/换行导致同义请求键不同，提升命中率。
    - 上下文指纹：键中仅使用「用户长期标签」排序列表，使相同请求+相同标签可命中；
      近三次交互通过 preference_context 在未命中时影响结果，不参与键以避免每次请求后键变导致永不命中。
    """
    request_data = {
        "user_id": _normalize_for_key(user_id),
        "brand_name": _normalize_for_key(brand_name),
        "product_desc": _normalize_for_key(product_desc),
        "topic": _normalize_for_key(topic),
    }
    if context_fingerprint is not None and context_fingerprint.get("tags"):
        request_data["tags"] = context_fingerprint["tags"]
    return "analyze:" + generate_cache_key(request_data)


class SmartCache:
    """
    使用 redis.asyncio 的智能缓存。
    get_or_set：有则返；无则 await coroutine_func() 得到结果，写入 Redis 后返回。
    """

    def __init__(self, redis_url: str | None = None) -> None:
        """
        Args:
            redis_url: Redis 连接串，默认从环境变量 REDIS_URL 读取。
        """
        url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = redis.Redis.from_url(url, decode_responses=True)

    async def get_or_set(
        self,
        key: str,
        coroutine_func: Callable[[], Awaitable[Any]],
        ttl: int = 3600,
    ) -> Tuple[Any, bool]:
        """
        若 key 在 Redis 中存在则反序列化并返回；否则 await coroutine_func() 得到结果，
        序列化写入 Redis（ttl 秒），再返回。

        Args:
            key: 缓存键，可由 generate_cache_key(request_data) 生成。
            coroutine_func: 无参异步可调用对象，返回可 JSON 序列化的结果；调用时需 await。
            ttl: 过期时间（秒），默认 3600。

        Returns:
            (结果, 是否命中缓存)：命中缓存为 (value, True)，未命中为 (value, False)。
        """
        raw = await self._redis.get(key)
        if raw is not None:
            try:
                return json.loads(raw), True
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("SmartCache get_or_set 反序列化失败 key=%s: %s", key, e)

        result = await coroutine_func()
        try:
            payload = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.warning("SmartCache get_or_set 序列化失败 key=%s: %s", key, e)
            return result, False
        await self._redis.setex(key, ttl, payload)
        return result, False

"""
智能缓存服务：缓存 AI 模型调用、知识库检索、记忆查询结果，使用 Redis（redis.asyncio）。
使用「请求指纹」作为键，支持更长 TTL（如 1 小时）；用户画像相关建议更短 TTL 或手动失效。
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

# TTL（秒）：AI/检索/记忆结果可较长；用户画像更新频繁，建议更短 TTL 或手动使缓存失效（避坑：缓存可能导致数据陈旧）
TTL_AI_DEFAULT = 3600  # 1 小时，AI 分析/生成等
TTL_ANALYSIS_WITH_PLUGINS = 300  # 5 分钟，带 analysis_plugins 的分析结果（含插件输出，略短 TTL 避免陈旧）
TTL_RETRIEVAL = 3600   # 1 小时，知识库检索
TTL_MEMORY = 3600      # 1 小时，记忆查询（若用户画像更新频繁，可改为 TTL_PROFILE 或写后 delete 键）
TTL_PROFILE = 300      # 5 分钟，仅用于「用户画像」类缓存；写后建议手动 delete 键
TTL_BILIBILI_HOTSPOT = 21600  # 6 小时，B站热点榜单报告缓存

# B站热点榜单报告 Redis 键（定时任务写入，策略调用时只读）
BILIBILI_HOTSPOT_CACHE_KEY = "bilibili_hotspot_report"


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


def build_fingerprint_key(prefix: str, request_data: dict) -> str:
    """
    使用「请求指纹」生成缓存键：对 request_data 中值做归一化后序列化哈希，再加前缀。
    用于 AI 调用、知识库检索、记忆查询等，保证同义请求命中同一键。
    """
    normalized = {k: _normalize_for_key(v) for k, v in request_data.items()}
    return prefix + generate_cache_key(normalized)


def build_analyze_cache_key(
    user_id: str,
    brand_name: str,
    product_desc: str,
    topic: str,
    context_fingerprint: dict | None = None,
) -> str:
    """
    生成分析缓存的 Redis 键（请求指纹）：请求四元组归一化 + 上下文指纹（仅用户标签参与键）。
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
    if context_fingerprint is not None:
        if context_fingerprint.get("tags"):
            request_data["tags"] = sorted(str(t) for t in context_fingerprint["tags"])
        if context_fingerprint.get("analysis_plugins") is not None:
            request_data["analysis_plugins"] = sorted(str(p) for p in context_fingerprint["analysis_plugins"])
    return build_fingerprint_key("analyze:", request_data)


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
        ttl: int | None = None,
    ) -> Tuple[Any, bool]:
        """
        若 key 在 Redis 中存在则反序列化并返回；否则 await coroutine_func() 得到结果，
        序列化写入 Redis（ttl 秒），再返回。键建议使用请求指纹 build_fingerprint_key 生成。

        Args:
            key: 缓存键，建议用 build_fingerprint_key(prefix, request_data) 生成。
            coroutine_func: 无参异步可调用对象，返回可 JSON 序列化的结果；调用时需 await。
            ttl: 过期时间（秒），默认 TTL_AI_DEFAULT（1 小时）；用户画像类建议用 TTL_PROFILE 或写后失效。

        Returns:
            (结果, 是否命中缓存)：命中缓存为 (value, True)，未命中为 (value, False)。
        """
        if ttl is None:
            ttl = TTL_AI_DEFAULT
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

    async def get(self, key: str) -> Any | None:
        """只读获取缓存，不写入。用于定时任务预热的只读场景。"""
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """写入缓存，用于定时任务预热。"""
        if ttl is None:
            ttl = TTL_AI_DEFAULT
        payload = json.dumps(value, ensure_ascii=False)
        await self._redis.setex(key, ttl, payload)

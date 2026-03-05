"""
记忆模块用 Embedding 封装：复用 config.api_config 的 embedding 配置，与 retrieval_service 行为一致。
供 MemoryService 写入/召回记忆条时使用，避免循环依赖。
"""
from __future__ import annotations

import logging
from typing import List

from openai import OpenAI

logger = logging.getLogger(__name__)

_embed_client: OpenAI | None = None


def _get_embed_client() -> OpenAI | None:
    """懒加载：根据 get_embedding_config 创建 OpenAI 兼容客户端。"""
    global _embed_client
    if _embed_client is not None:
        return _embed_client
    try:
        from config.api_config import get_embedding_config
        cfg = get_embedding_config()
        c = OpenAI(api_key=cfg.get("api_key") or "", base_url=cfg.get("base_url"))
        _embed_client = c
        return _embed_client
    except Exception as e:
        logger.warning("记忆模块 embedding 客户端初始化失败: %s", e)
        return None


def get_embedding(text: str) -> List[float] | None:
    """
    对文本做向量化，与 retrieval_service 使用同一配置。
    若未配置 API 或调用失败，返回 None。
    """
    client = _get_embed_client()
    if client is None:
        return None
    if not (text or "").strip():
        return None
    try:
        from config.api_config import get_embedding_config
        cfg = get_embedding_config()
        response = client.embeddings.create(model=cfg.get("model", "text-embedding-3-small"), input=text.strip())
        return list(response.data[0].embedding)
    except Exception as e:
        logger.warning("记忆模块 get_embedding 失败: %s", e)
        return None

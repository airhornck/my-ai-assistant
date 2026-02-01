"""
向量检索服务：从知识库查找相关段落，支持 RAG。
使用阿里云 Dashscope 嵌入 API + numpy 实现简单向量检索，避免 chromadb/sentence-transformers 兼容性问题。
向量持久化到 JSON，首次运行需初始化。可选 SmartCache，以请求指纹为键、长 TTL 缓存检索结果。
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import List, TYPE_CHECKING

import numpy as np
from openai import OpenAI

# 统一接口配置入口：config/api_config，引用 embedding 接口
from config.api_config import get_embedding_config

if TYPE_CHECKING:
    from cache.smart_cache import SmartCache

logger = logging.getLogger(__name__)

# 向量库持久化路径
DEFAULT_PERSIST_DIR = os.getenv("KNOWLEDGE_VECTOR_DIR", "./data/knowledge_vectors")
# 知识库路径
DEFAULT_KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", "./knowledge")
# 检索返回段落数
DEFAULT_TOP_K = 4
# 分块大小
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


class RetrievalService:
    """
    从知识库检索相关段落。首次调用会初始化向量库（加载文档、分块、嵌入）。
    使用 Dashscope 嵌入 API + numpy 余弦相似度，轻量级方案，兼容 Python 3.14。
    """

    def __init__(
        self,
        knowledge_dir: str | None = None,
        persist_dir: str | None = None,
        top_k: int = DEFAULT_TOP_K,
        cache: "SmartCache | None" = None,
    ) -> None:
        self._knowledge_dir = Path(knowledge_dir or DEFAULT_KNOWLEDGE_DIR)
        self._persist_dir = Path(persist_dir or DEFAULT_PERSIST_DIR)
        self._top_k = top_k
        self._cache = cache
        self._chunks: List[dict] = []  # [{"text": str, "vector": list}, ...]
        self._initialized = False
        try:
            embed_cfg = get_embedding_config()
            self._embed_client = OpenAI(api_key=embed_cfg["api_key"], base_url=embed_cfg["base_url"])
        except ValueError as e:
            logger.warning("嵌入配置加载失败，检索功能不可用: %s", e)
            self._embed_client = None

    def _load_markdown_files(self) -> List[str]:
        """加载知识库目录下的所有 .md 文件内容。"""
        if not self._knowledge_dir.exists():
            logger.warning("知识库目录不存在: %s", self._knowledge_dir)
            return []
        texts = []
        for md_file in self._knowledge_dir.glob("**/*.md"):
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    texts.append(f.read())
            except Exception as e:
                logger.warning("读取 %s 失败: %s", md_file, e)
        return texts

    def _chunk_text(self, text: str) -> List[str]:
        """简单分块：按段落 + 固定大小分块，带重叠。"""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        for para in paragraphs:
            if len(para) <= CHUNK_SIZE:
                chunks.append(para)
            else:
                for i in range(0, len(para), CHUNK_SIZE - CHUNK_OVERLAP):
                    chunk = para[i : i + CHUNK_SIZE]
                    if chunk.strip():
                        chunks.append(chunk.strip())
        return chunks

    def _get_embedding(self, text: str) -> List[float] | None:
        """调用 Dashscope 嵌入 API 获取向量。"""
        if self._embed_client is None:
            logger.warning("嵌入客户端未初始化（API Key 未配置），无法生成嵌入")
            return None
        try:
            embed_cfg = get_embedding_config()
            response = self._embed_client.embeddings.create(model=embed_cfg["model"], input=text)
            return response.data[0].embedding
        except Exception as e:
            logger.warning("嵌入 API 调用失败: %s", e)
            return None

    def _build_and_persist(self) -> None:
        """加载知识库文档、分块、嵌入并持久化到 JSON。"""
        texts = self._load_markdown_files()
        if not texts:
            logger.warning("知识库无文档，向量库为空")
            self._chunks = []
            self._initialized = True
            return
        all_chunks = []
        for text in texts:
            all_chunks.extend(self._chunk_text(text))
        logger.info("知识库共 %d 个文档，分块 %d 个，开始嵌入...", len(texts), len(all_chunks))
        chunks_with_vectors = []
        for i, chunk in enumerate(all_chunks):
            vec = self._get_embedding(chunk)
            if vec is None:
                continue
            chunks_with_vectors.append({"text": chunk, "vector": vec})
            if (i + 1) % 10 == 0:
                logger.info("已嵌入 %d/%d", i + 1, len(all_chunks))
        self._chunks = chunks_with_vectors
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        persist_file = self._persist_dir / "vectors.json"
        with open(persist_file, "w", encoding="utf-8") as f:
            json.dump(self._chunks, f, ensure_ascii=False, indent=2)
        logger.info("向量库已持久化到 %s，共 %d 个向量", persist_file, len(self._chunks))
        self._initialized = True

    def _ensure_initialized(self) -> None:
        """懒加载：若向量库未初始化则构建并持久化。"""
        if self._initialized:
            return
        persist_file = self._persist_dir / "vectors.json"
        if persist_file.exists():
            try:
                with open(persist_file, "r", encoding="utf-8") as f:
                    self._chunks = json.load(f)
                logger.info("RetrievalService 从持久化文件加载向量库: %s，共 %d 个向量", persist_file, len(self._chunks))
                self._initialized = True
                return
            except Exception as e:
                logger.warning("加载已有向量库失败，将重建: %s", e)
        self._build_and_persist()

    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
    ) -> List[str]:
        """
        根据查询检索相关段落，使用余弦相似度排序。
        若注入 SmartCache，则按请求指纹（query + top_k）缓存，TTL 见 TTL_RETRIEVAL。
        若 API Key 未配置或嵌入失败，返回空列表。
        """
        if self._embed_client is None:
            logger.warning("嵌入客户端未初始化（API Key 未配置），跳过检索")
            return []
        k = top_k if top_k is not None else self._top_k
        if k <= 0:
            return []

        async def _do_retrieve() -> List[str]:
            try:
                self._ensure_initialized()
                if not self._chunks:
                    return []
                query_vec = self._get_embedding(query)
                if query_vec is None:
                    return []
                query_arr = np.array(query_vec)
                similarities = []
                for chunk in self._chunks:
                    chunk_arr = np.array(chunk["vector"])
                    sim = np.dot(query_arr, chunk_arr) / (np.linalg.norm(query_arr) * np.linalg.norm(chunk_arr) + 1e-9)
                    similarities.append((sim, chunk["text"]))
                similarities.sort(reverse=True, key=lambda x: x[0])
                return [text for _, text in similarities[:k]]
            except Exception as e:
                logger.warning("RetrievalService.retrieve 失败: %s", e, exc_info=True)
                return []

        if self._cache is not None:
            from cache.smart_cache import build_fingerprint_key, TTL_RETRIEVAL
            key = build_fingerprint_key("retrieval:", {"query": _normalize_query_for_key(query), "top_k": k})
            result, hit = await self._cache.get_or_set(key, _do_retrieve, ttl=TTL_RETRIEVAL)
            if hit:
                logger.debug("retrieve 缓存命中 key=%s", key)
            return result
        return await _do_retrieve()

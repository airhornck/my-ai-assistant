"""
知识库 Port：检索接口抽象，与实现（本地向量 / 阿里云百炼）解耦。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class KnowledgePort(ABC):
    """知识库检索端口：按 query 检索相关段落，用于 RAG 注入。"""

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        top_k: int = 4,
        **kwargs: object,
    ) -> List[str]:
        """
        根据查询检索相关段落。
        :param query: 检索 query（如 品牌+主题+产品）
        :param top_k: 返回条数
        :return: 段落文本列表，按相关度排序
        """
        ...

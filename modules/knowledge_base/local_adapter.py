"""
知识库本地适配器：基于现有 RetrievalService（向量 JSON），用于开发/本地环境。
"""
from __future__ import annotations

from typing import List, TYPE_CHECKING

from services.retrieval_service import RetrievalService

if TYPE_CHECKING:
    from cache.smart_cache import SmartCache


class LocalKnowledgeAdapter(RetrievalService):
    """本地知识库：继承 RetrievalService，实现 KnowledgePort。"""

    def __init__(
        self,
        knowledge_dir: str | None = None,
        persist_dir: str | None = None,
        top_k: int = 4,
        cache: "SmartCache | None" = None,
    ) -> None:
        super().__init__(
            knowledge_dir=knowledge_dir,
            persist_dir=persist_dir,
            top_k=top_k,
            cache=cache,
        )

    async def retrieve(
        self,
        query: str,
        top_k: int = 4,
        **kwargs: object,
    ) -> List[str]:
        return await RetrievalService.retrieve(self, query, top_k=top_k)

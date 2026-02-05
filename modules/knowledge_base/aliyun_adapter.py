"""
知识库阿里云适配器：对接阿里云百炼知识库（RAG）Retrieve API，用于生产环境。
环境变量示例：ALIYUN_BAILIAN_WORKSPACE_ID、ALIYUN_BAILIAN_INDEX_ID、ALIYUN_BAILIAN_*。
未配置或调用失败时降级返回空列表，不阻塞主流程。
"""
from __future__ import annotations

import logging
import os
from typing import List

from modules.knowledge_base.port import KnowledgePort

logger = logging.getLogger(__name__)


class AliyunKnowledgeAdapter(KnowledgePort):
    """阿里云百炼知识库检索适配器。"""

    def __init__(
        self,
        workspace_id: str | None = None,
        index_id: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._workspace_id = workspace_id or os.getenv("ALIYUN_BAILIAN_WORKSPACE_ID")
        self._index_id = index_id or os.getenv("ALIYUN_BAILIAN_INDEX_ID")
        self._timeout = timeout

    async def retrieve(
        self,
        query: str,
        top_k: int = 4,
        **kwargs: object,
    ) -> List[str]:
        """
        调用阿里云百炼 Retrieve API。未配置或异常时返回 []，保证不阻塞。
        """
        if not self._workspace_id or not self._index_id:
            logger.warning("阿里云知识库未配置 WORKSPACE_ID/INDEX_ID，跳过检索")
            return []
        try:
            # 此处接入阿里云百炼 SDK：Retrieve API
            # 示例（需安装 alibabacloud_bailian 等）：client.retrieve(WorkspaceId=..., IndexId=..., Query=..., TopK=...)
            # 返回格式转为 List[str]（段落文本）
            logger.info("AliyunKnowledgeAdapter.retrieve query=%s top_k=%s", query[:50], top_k)
            # 占位：实际实现时替换为真实 API 调用
            return []
        except Exception as e:
            logger.warning("阿里云知识库检索失败，降级返回空: %s", e)
            return []

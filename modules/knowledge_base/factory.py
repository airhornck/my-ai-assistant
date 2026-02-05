"""
知识库工厂：按环境变量选择本地或阿里云实现，便于单独开发与生产切换。
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from modules.knowledge_base.port import KnowledgePort
from modules.knowledge_base.local_adapter import LocalKnowledgeAdapter
from modules.knowledge_base.aliyun_adapter import AliyunKnowledgeAdapter

if TYPE_CHECKING:
    from cache.smart_cache import SmartCache


def get_knowledge_port(cache: "SmartCache | None" = None) -> KnowledgePort:
    """
    生产环境且配置了阿里云知识库时使用 AliyunKnowledgeAdapter，否则使用 LocalKnowledgeAdapter。
    环境变量：USE_ALIYUN_KNOWLEDGE=1 且 ALIYUN_BAILIAN_WORKSPACE_ID、ALIYUN_BAILIAN_INDEX_ID 已配置。
    """
    use_aliyun = os.getenv("USE_ALIYUN_KNOWLEDGE", "").strip() == "1"
    workspace = os.getenv("ALIYUN_BAILIAN_WORKSPACE_ID", "").strip()
    index_id = os.getenv("ALIYUN_BAILIAN_INDEX_ID", "").strip()
    if use_aliyun and workspace and index_id:
        return AliyunKnowledgeAdapter(workspace_id=workspace, index_id=index_id)
    return LocalKnowledgeAdapter(cache=cache)

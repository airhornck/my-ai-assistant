"""
知识库模块：RAG 检索与案例检索抽象，可对接本地向量或阿里云百炼知识库。
"""
from modules.knowledge_base.port import KnowledgePort
from modules.knowledge_base.local_adapter import LocalKnowledgeAdapter
from modules.knowledge_base.aliyun_adapter import AliyunKnowledgeAdapter
from modules.knowledge_base.factory import get_knowledge_port

__all__ = [
    "KnowledgePort",
    "LocalKnowledgeAdapter",
    "AliyunKnowledgeAdapter",
    "get_knowledge_port",
]

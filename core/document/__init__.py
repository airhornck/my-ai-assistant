"""
文档能力模块：存储、解析、会话绑定。
解耦设计，便于生产环境维护和扩展（如切换 OSS、更换解析引擎）。
"""
from core.document.storage import DocumentStorage
from core.document.parser import DocumentParser
from core.document.session_binding import SessionDocumentBinding

__all__ = [
    "DocumentStorage",
    "DocumentParser",
    "SessionDocumentBinding",
]

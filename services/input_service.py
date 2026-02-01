"""
输入处理服务：意图识别与输入标准化。
本模块为 core.intent 的兼容层，保留原有导入路径，便于渐进迁移。
"""
from __future__ import annotations

from core.intent import (
    INTENT_CASUAL_CHAT,
    INTENT_COMMAND,
    INTENT_DOCUMENT_QUERY,
    INTENT_FREE_DISCUSSION,
    INTENT_STRUCTURED_REQUEST,
    InputProcessor,
)

__all__ = [
    "InputProcessor",
    "INTENT_CASUAL_CHAT",
    "INTENT_COMMAND",
    "INTENT_DOCUMENT_QUERY",
    "INTENT_FREE_DISCUSSION",
    "INTENT_STRUCTURED_REQUEST",
]

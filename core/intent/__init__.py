"""
意图理解模块：从用户输入识别意图并标准化。
解耦设计，便于维护和替换分类逻辑。
"""
from core.intent.processor import InputProcessor
from core.intent.types import (
    INTENT_CASUAL_CHAT,
    INTENT_COMMAND,
    INTENT_DOCUMENT_QUERY,
    INTENT_FREE_DISCUSSION,
    INTENT_STRUCTURED_REQUEST,
)

__all__ = [
    "InputProcessor",
    "INTENT_CASUAL_CHAT",
    "INTENT_COMMAND",
    "INTENT_DOCUMENT_QUERY",
    "INTENT_FREE_DISCUSSION",
    "INTENT_STRUCTURED_REQUEST",
]

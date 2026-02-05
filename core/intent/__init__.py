"""
意图理解模块：从用户输入识别意图并标准化。
解耦设计，便于维护和替换分类逻辑。
"""
from core.intent.feedback_classifier import (
    AMBIGUOUS_FEEDBACK_PHRASES,
    ACCEPT_SUGGESTION_PHRASES,
    FeedbackIntentResult,
    classify_feedback_after_creation,
)
from core.intent.marketing_intent_classifier import (
    ClassificationResult,
    MarketingIntentClassifier,
)
from core.intent.processor import InputProcessor, SHORT_CASUAL_REPLIES
from core.intent.types import (
    INTENT_CASUAL_CHAT,
    INTENT_COMMAND,
    INTENT_DOCUMENT_QUERY,
    INTENT_FREE_DISCUSSION,
    INTENT_STRUCTURED_REQUEST,
)

__all__ = [
    "ACCEPT_SUGGESTION_PHRASES",
    "AMBIGUOUS_FEEDBACK_PHRASES",
    "ClassificationResult",
    "FeedbackIntentResult",
    "InputProcessor",
    "classify_feedback_after_creation",
    "INTENT_CASUAL_CHAT",
    "INTENT_COMMAND",
    "INTENT_DOCUMENT_QUERY",
    "INTENT_FREE_DISCUSSION",
    "INTENT_STRUCTURED_REQUEST",
    "MarketingIntentClassifier",
    "SHORT_CASUAL_REPLIES",
]

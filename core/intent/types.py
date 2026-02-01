"""
意图类型与常量定义。
"""

INTENT_STRUCTURED_REQUEST = "structured_request"
INTENT_FREE_DISCUSSION = "free_discussion"
INTENT_CASUAL_CHAT = "casual_chat"
INTENT_DOCUMENT_QUERY = "document_query"
INTENT_COMMAND = "command"

DEFAULT_INTENT = INTENT_FREE_DISCUSSION
STRUCTURED_DATA_KEYS = ("brand_name", "product_desc", "topic")

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from services.ai_service import SimpleAIService
from core.intent.marketing_intent_classifier import MarketingIntentClassifier
from core.intent.types import (
    DEFAULT_INTENT,
    INTENT_CASUAL_CHAT,
    INTENT_COMMAND,
    INTENT_DOCUMENT_QUERY,
    INTENT_FREE_DISCUSSION,
    INTENT_STRUCTURED_REQUEST,
    STRUCTURED_DATA_KEYS,
)

logger = logging.getLogger(__name__)

COMMAND_PATTERN = re.compile(r"^\s*/(\w+)(?:/\w+)*(?:\s|$)", re.IGNORECASE)

SHORT_CASUAL_REPLIES = frozenset((
    "你好", "您好", "嗨", "在吗", "哈喽",
    "还好", "还好吧", "嗯", "不错", "还行", "一般",
))

EXPLICIT_CONTENT_PHRASES = (
    "生成", "写一篇", "帮我写", "做个文案", "输出文案", "给我一篇",
    "写个", "写段", "写一个", "出一篇", "创作", "帮我做", "生成一篇",
    "写份", "输出一篇", "小红书文案", "抖音脚本", "B站文案", "微博文案",
    "知乎文章", "推广文案", "推广脚本", "推广文章", "营销文案", "营销脚本",
    "多平台", "多个平台", "三个平台", "各平台", "帮我推广", "帮我制定",
    "制定一个", "帮我创建",
)

STRUCTURED_KEYWORDS = {
    "brand": ("品牌是", "品牌叫", "品牌名", "品牌", "我的是", "我叫"),
    "product": ("产品是", "产品叫", "产品名", "产品", "卖的是"),
    "topic": ("主题是", "话题是", "目标", "目的是", "推广", "想做"),
}

STRUCTURED_PATTERNS = [
    r"品牌[是为叫名][^，。,]{2,20}",
    r"产品[是为叫名][^，。,]{2,30}",
    r"主题[是为][^，。,]{2,20}",
    r"目标.{0,10}(人群|用户|用户群体)",
    r"品牌[^\s]{2,30}产品[^\s]{2,30}",
]

def _parse_command(raw_input: str) -> Optional[str]:
    m = COMMAND_PATTERN.match((raw_input or "").strip())
    return m.group(1) if m else None

def _has_explicit_content_request(text: str) -> bool:
    t = (text or "").strip()
    return any(p in t for p in EXPLICIT_CONTENT_PHRASES)

def _is_structured_request(text: str) -> bool:
    t = (text or "").strip()
    has_brand = any(kw in t for kw in STRUCTURED_KEYWORDS["brand"])
    has_product = any(kw in t for kw in STRUCTURED_KEYWORDS["product"])
    has_topic = any(kw in t for kw in STRUCTURED_KEYWORDS["topic"])
    if has_brand and (has_product or has_topic):
        return True
    for pattern in STRUCTURED_PATTERNS:
        if re.search(pattern, t):
            return True
    return False

def _normalize_structured_data(data: dict) -> dict[str, str]:
    out = {k: "" for k in STRUCTURED_DATA_KEYS}
    for k in STRUCTURED_DATA_KEYS:
        v = data.get(k)
        if v is not None and isinstance(v, str):
            out[k] = v.strip()
    return out

def _extract_self_intro(raw: str) -> dict[str, str]:
    t = (raw or "").strip()
    out = {"brand_name": "", "topic": ""}
    m1 = re.search(r"我叫([^，。！？\s]{2,20})", t)
    if m1:
        out["brand_name"] = m1.group(1).strip()[:64]
    m2 = re.search(r"我是(?:做)?([^的。！？\s]{2,20})(?:的|行业)?", t)
    if m2:
        out["topic"] = m2.group(1).strip()[:64]
    return out

def _looks_like_product_mention(text: str) -> bool:
    t = (text or "").strip()
    product_words = ("手机", "耳机", "电脑", "平板", "手表", "咖啡", "奶茶", "零食", "护肤品")
    return len(t) >= 5 and any(w in t for w in product_words)

def _parse_intent_response(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    for prefix in ("```json", "```"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
    if raw.endswith("```"):
        raw = raw[:raw.rfind("```")].strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}

class InputProcessor:
    def __init__(self, ai_service: Optional[SimpleAIService] = None, use_rule_based_intent_filter: bool = True):
        self._ai = ai_service or SimpleAIService()
        self._use_rule_based_filter = use_rule_based_intent_filter
        self._marketing_classifier = MarketingIntentClassifier(use_fallback_llm=False)

    async def process(
        self,
        raw_input: str,
        session_id: str = "",
        user_id: str = "",
        conversation_context: Optional[str] = None,
        session_document_context: Optional[str] = None,
    ) -> dict[str, Any]:
        raw = (raw_input or "").strip()
        base = {
            "intent": DEFAULT_INTENT,
            "session_id": session_id or "",
            "user_id": user_id or "",
            "structured_data": {},
            "raw_query": raw,
            "command": None,
            "explicit_content_request": False,
        }
        if not raw:
            return base

        # 命令判定
        cmd = _parse_command(raw)
        if cmd:
            base["intent"] = INTENT_COMMAND
            base["command"] = cmd
            return base

        # 短闲聊判定
        has_marketing_kw = any(kw in raw for kw in ("推广", "营销", "文案", "品牌", "产品", "宣传", "卖", "带货", "种草"))
        if raw in SHORT_CASUAL_REPLIES and not has_marketing_kw:
            base["intent"] = INTENT_CASUAL_CHAT
            return base

        # 规则分类器判定闲聊
        if self._use_rule_based_filter:
            rule_result = self._marketing_classifier.classify(raw, session_id=session_id or None, conversation_history=None)
            if not rule_result.is_marketing and rule_result.confidence >= 0.75:
                base["intent"] = INTENT_CASUAL_CHAT
                return base

        # 构建 LLM 输入
        user_input_for_classify = raw
        if conversation_context:
            user_input_for_classify = f"【近期对话上下文】\n{conversation_context.strip()}\n\n【用户当前输入】\n{raw}"

        # 调用 LLM 分类
        try:
            client = await self._ai.router.route("planning", "low")
            messages = [
                SystemMessage(content="你是意图分类器，请只输出 JSON 对象。"),
                HumanMessage(content=f"用户输入：\n{user_input_for_classify}"),
            ]
            response = await client.ainvoke(messages)
            parsed = _parse_intent_response(response.content)
        except Exception:
            parsed = {}

        intent = parsed.get("intent", "").lower() or DEFAULT_INTENT

        # 修正短闲聊
        if raw in SHORT_CASUAL_REPLIES and not has_marketing_kw:
            intent = INTENT_CASUAL_CHAT

        # 结构化请求优先判定
        if intent in (DEFAULT_INTENT, INTENT_FREE_DISCUSSION) and _is_structured_request(raw):
            intent = INTENT_STRUCTURED_REQUEST

        # explicit_content_request 规则优先
        explicit_request = _has_explicit_content_request(raw)
        # 自由讨论或结构化请求中提到平台关键词，也判为 True
        platform_keywords = ("小红书", "抖音", "B站", "b站", "微博", "知乎", "快手", "视频号", "文案", "脚本", "推广")
        if intent in (INTENT_STRUCTURED_REQUEST, INTENT_FREE_DISCUSSION) and any(kw in raw for kw in platform_keywords):
            explicit_request = True

        base["intent"] = intent
        base["explicit_content_request"] = explicit_request

        # 提取结构化信息
        sd = _normalize_structured_data(parsed)
        if not any(sd.values()):
            intro = _extract_self_intro(raw)
            sd.update({k: v for k, v in intro.items() if v})
        base["structured_data"] = {k: v for k, v in sd.items() if v} if any(sd.values()) else {}

        return base
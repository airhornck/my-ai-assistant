"""
意图处理器：意图识别与输入标准化。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

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
from services.ai_service import SimpleAIService

logger = logging.getLogger(__name__)

# 支持 /command 和 /command/subcommand 格式
COMMAND_PATTERN = re.compile(r"^\s*/(\w+)(?:/\w+)*(?:\s|$)", re.IGNORECASE)

INTENT_CLASSIFY_SYSTEM = """你是一个输入意图分类器。根据用户输入（可能包含近期对话上下文）判断意图类型，并按要求输出唯一一个 JSON 对象。

**文档与链接的处理原则**
- 会话中提交的文档或链接，**仅作为会话内容的补充**，不改变主意图与主推广对象。
- 文档/链接会由系统解析后与会话意图合并，作为后续生成的参考资料，**延续上下文继续执行**。
- 主推广对象（brand_name、product_desc、topic）**始终且仅从【近期对话上下文】和【用户当前输入】**中提取。
- 若参考资料中的品牌/产品与对话中用户明确要推广的内容不同，以用户对话为准。例如：用户说「推广华为手机」并附链接，链接若写 vivo，则 brand_name/product_desc 填华为，不能填 vivo。

类型说明（必须严格区分）：
- casual_chat：日常闲聊、非营销对话。如：问候（你好/嗨/在吗）、感谢/告别（谢谢/再见）、简单咨询（你有什么功能/怎么用）、随便聊聊、天气等无关营销的话题。**关键**：若用户当前输入包含「推广」（=营销推广，≠推荐机型）、「营销」「文案」「品牌」「产品」「宣传」「卖」等词，或明确提到具体产品/品牌（如「华为手机」「降噪耳机」），则**绝不**判为 casual_chat。
- structured_request：用户直接给出了结构化的品牌、产品、话题信息（如「品牌XX，产品是YY，想推广ZZ」或明确列出品牌名、产品描述、主题）。
- free_discussion：用户在讨论营销想法或需求，涉及产品/推广/文案，但未完全结构化。**典型示例**：「推广华为手机」「推广降噪耳机」「帮我写个文案」「营销IP搭建」——此类一律判 free_discussion，绝不判 casual_chat。
- document_query：用户的问题**明确以文档为主体**（如「根据我上传的PPT总结品牌优势」「用文档写介绍」）。注意：若对话中已确立推广主题（如「推广华为手机」），用户再附加文档/链接作为参考时，应延续原有意图（structured_request 或 free_discussion），文档/链接仅为补充，不判为 document_query。
- command：用户在执行命令（如以 / 开头的「/new_chat」「/summarize 总结历史」等）。

**explicit_content_request（关键）**：用户是否**明确要求生成具体内容**（文案、文章、脚本等）？
- true：用户明确说了「生成」「写一篇」「帮我写」「做个文案」「输出」「给我一篇」「写个」「写段」等，或指定了平台+篇幅（如「小红书文案」「B站脚本」）。
- false：用户只是陈述话题、目标人群、推广意向，**未明确要求产出具体内容**。如「推广华为手机，年龄18-35」→ false；「推广华为手机，帮我生成一篇小红书文案」→ true。

**用户自我介绍（用于长期记忆）**：若用户说「我叫X」「我是做X的」「我是X行业」等，请提取：brand_name 填名字/称呼，topic 填行业或身份。即使用户在闲聊也请提取，供跨会话记忆。

输出要求：
只输出一个 JSON 对象，不要任何其他文字、说明或 markdown。必须用三个反引号包裹，格式为：```json
{ "intent": "上述五类之一", "brand_name": "仅当可明确提取时填写，否则空字符串", "product_desc": "同上", "topic": "同上", "command": "仅当 intent 为 command 时填写命令名如 new_chat，否则空字符串", "explicit_content_request": true 或 false }
```
判断要点：若用户只是在打招呼、闲聊、选 casual_chat；若涉及产品/品牌/推广但**未明确要求生成内容**，explicit_content_request 必须为 false。"""


def _parse_intent_response(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    for prefix in ("```json", "```"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :].strip()
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")].strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError) as e:
        logger.warning("意图识别 JSON 解析失败: %s raw=%s", e, raw[:300])
        return {}


def _normalize_structured_data(data: dict) -> dict[str, str]:
    out = {k: "" for k in STRUCTURED_DATA_KEYS}
    for k in STRUCTURED_DATA_KEYS:
        v = data.get(k)
        if v is not None and isinstance(v, str):
            out[k] = v.strip()
    return out


# 简短闲聊回复/问候：仅当用户当前输入为此类短句时，直接判为 casual_chat，不调用 LLM，避免误判为创作
# 不含「可以」「好的」「行」等，因可能表示采纳建议，需走 main 的采纳逻辑
# 含常见问候（你好/嗨/在吗）与简短寒暄（还好/嗯），保证「你好」「还好」等先后问话正确识别为闲聊
SHORT_CASUAL_REPLIES = frozenset((
    "你好", "您好", "嗨", "在吗", "哈喽",  # 问候
    "还好", "还好吧", "嗯", "不错", "还行", "一般",  # 简短寒暄
))


# 明确要求生成内容的触发词（出现则 explicit_content_request=true）
EXPLICIT_CONTENT_PHRASES = (
    "生成", "写一篇", "帮我写", "做个文案", "输出文案", "给我一篇", "写个", "写段",
    "写一个", "出一篇", "创作", "帮我做", "生成一篇", "写份", "输出一篇",
    "小红书文案", "抖音脚本", "B站文案", "微博文案", "知乎文章",  # 平台+内容类型
)

# 结构化请求关键词组合（出现多个则判定为 structured_request）
STRUCTURED_KEYWORDS = {
    "brand": ("品牌是", "品牌叫", "品牌名", "品牌", "我的是", "我叫"),
    "product": ("产品是", "产品叫", "产品名", "产品", "卖的是"),
    "topic": ("主题是", "话题是", "目标", "目的是", "推广", "想做"),
}

# 结构化请求模式（正则）
# 注意：只匹配明确给出结构化信息的模式，不匹配模糊的推广意图
STRUCTURED_PATTERNS = [
    r"品牌[是为叫名][^，。,]{2,20}",  # 品牌是XXX（排除常见分隔符）
    r"产品[是为叫名][^，。,]{2,30}",  # 产品是XXX
    r"主题[是为][^，。,]{2,20}",      # 主题是XXX
    r"目标.{0,10}(人群|用户|用户群体)",  # 目标人群
    r"品牌[^\s]{2,30}产品[^\s]{2,30}",  # 品牌XXX产品XXX（同时出现）
]


def _has_explicit_content_request(text: str) -> bool:
    """用户是否明确要求生成具体内容（规则兜底，优先于 LLM 判断）。"""
    t = (text or "").strip()
    return any(p in t for p in EXPLICIT_CONTENT_PHRASES)


def _is_structured_request(text: str) -> bool:
    """判断是否为结构化请求（包含品牌+产品等结构化信息）。"""
    t = (text or "").strip()
    
    # 检查是否包含结构化关键词组合
    # 注意：需要同时有 brand 和 product，或者同时有 brand 和 topic，才是真正的结构化请求
    has_brand = any(kw in t for kw in STRUCTURED_KEYWORDS["brand"])
    has_product = any(kw in t for kw in STRUCTURED_KEYWORDS["product"])
    has_topic = any(kw in t for kw in STRUCTURED_KEYWORDS["topic"])
    
    # 必须同时有 brand + product，或者 brand + topic，才是结构化请求
    # 不能只有 topic（推广我的产品）就判断为结构化
    if has_brand and (has_product or has_topic):
        return True
    if has_product and has_brand:
        return True
    
    # 检查正则模式
    for pattern in STRUCTURED_PATTERNS:
        if re.search(pattern, t):
            return True
    
    return False


def _extract_self_intro(raw: str) -> dict[str, str]:
    """规则提取自我介绍：我叫X、我是做X的，供长期记忆。"""
    t = (raw or "").strip()
    out = {"brand_name": "", "topic": ""}
    # 我叫X（X为2-20字符）
    m1 = re.search(r"我叫([^，。！？\s]{2,20})", t)
    if m1:
        out["brand_name"] = m1.group(1).strip()[:64]
    # 我是做X的 / 我是X行业的
    m2 = re.search(r"我是(?:做)?([^的。！？\s]{2,20})(?:的|行业)?", t)
    if m2:
        out["topic"] = m2.group(1).strip()[:64]
    return out


def _looks_like_product_mention(text: str) -> bool:
    """是否像在提及具体产品/品牌（如「华为手机」「降噪耳机」），用于意图修正。"""
    t = (text or "").strip()
    if len(t) < 4:
        return False
    # 品牌+产品模式（如「华为手机」「小米耳机」）或 产品词+名词
    product_words = ("手机", "耳机", "电脑", "平板", "手表", "咖啡", "奶茶", "零食", "护肤品")
    return any(w in t for w in product_words) and len(t) >= 5


def _parse_command(raw_input: str) -> Optional[str]:
    m = COMMAND_PATTERN.match((raw_input or "").strip())
    return m.group(1) if m else None


class InputProcessor:
    """
    输入处理器：意图识别 + 输入标准化。
    优先使用规则+关键词的营销意图分类器，减少 LLM 误判；对复杂情况再调用 LLM 做细粒度分类与结构化数据提取。
    """

    def __init__(
        self,
        ai_service: Optional[SimpleAIService] = None,
        use_rule_based_intent_filter: bool = True,
    ) -> None:
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
        """
        处理用户原始输入：意图识别 → 输入标准化。
        conversation_context: 近期对话上下文，主推广对象从此提取。
        session_document_context: 会话中附加的文档/链接内容。意图识别时不下发（文档/链接仅为补充，
            由调用方解析后与会话意图合并，延续上下文执行）。保留参数以兼容调用签名。
        """
        raw = (raw_input or "").strip()
        base = {
            "intent": DEFAULT_INTENT,
            "session_id": session_id or "",
            "user_id": user_id or "",
            "structured_data": {},
            "raw_query": raw,
            "command": None,
            "analysis_plugin_result": None,
        }

        if not raw:
            return base

        cmd = _parse_command(raw)
        if cmd:
            base["intent"] = INTENT_COMMAND
            base["command"] = cmd
            base["raw_query"] = raw
            return base

        # 简短闲聊回复：直接判为 casual_chat，不调用 LLM，避免「还好」等被误判为 free_discussion
        raw_clean = (raw or "").strip()
        if raw_clean in SHORT_CASUAL_REPLIES and len(raw_clean) <= 8:
            base["intent"] = INTENT_CASUAL_CHAT
            base["raw_query"] = raw
            base["structured_data"] = {}
            logger.info("意图识别: 简短闲聊回复，直接 casual_chat, raw=%s", raw_clean)
            return base

        # 规则+关键词的营销意图分类器：明确闲聊时直接返回，避免 LLM 误判（如「今天天气不错」「谢谢」等）
        if self._use_rule_based_filter:
            rule_result = self._marketing_classifier.classify(
                raw, session_id=session_id or None, conversation_history=None
            )
            if not rule_result.is_marketing and rule_result.confidence >= 0.75:
                base["intent"] = INTENT_CASUAL_CHAT
                base["raw_query"] = raw
                base["structured_data"] = {}
                base["explicit_content_request"] = False
                logger.info(
                    "意图识别: 规则分类器判定闲聊, raw=%s, conf=%.2f, reason=%s",
                    raw[:50], rule_result.confidence, rule_result.reason,
                )
                return base

        # 意图与主推广对象仅从对话提取，不传入文档/链接内容，避免参考材料中的其他产品干扰
        user_input_for_classify = raw
        ctx_parts = []
        if conversation_context and conversation_context.strip():
            ctx_parts.append(f"【近期对话上下文】\n{conversation_context.strip()}")
        if ctx_parts:
            user_input_for_classify = "\n\n".join(ctx_parts) + f"\n\n【用户当前输入】\n{raw}"

        try:
            client = await self._ai.router.route("planning", "low")
            messages = [
                SystemMessage(content=INTENT_CLASSIFY_SYSTEM),
                HumanMessage(content=f"用户输入：\n{user_input_for_classify}"),
            ]
            response = await client.ainvoke(messages)
            text = (response.content or "").strip()
        except Exception as e:
            logger.warning("意图识别 AI 调用失败，降级为 free_discussion: %s", e, exc_info=True)
            base["intent"] = DEFAULT_INTENT
            base["raw_query"] = raw
            return base

        parsed = _parse_intent_response(text)
        intent = (parsed.get("intent") or "").strip().lower()
        # 硬性修正：若 LLM 误判，简短闲聊回复（如「还好」「嗯」）仍强制为 casual_chat
        if intent != INTENT_CASUAL_CHAT and (raw_clean := (raw or "").strip()) in SHORT_CASUAL_REPLIES and len(raw_clean) <= 8:
            intent = INTENT_CASUAL_CHAT
            logger.info("意图修正: 简短闲聊回复 -> casual_chat, raw=%s", raw_clean)
        # 硬性修正：含营销关键词时绝不判为闲聊
        _marketing_kw = ("推广", "营销", "文案", "品牌", "产品", "宣传", "卖", "带货", "种草")
        if intent == INTENT_CASUAL_CHAT and raw:
            if any(kw in raw for kw in _marketing_kw) or (_looks_like_product_mention(raw)):
                intent = DEFAULT_INTENT
                logger.info("意图修正: casual_chat -> %s (含营销关键词)", intent)
        
        # 硬性修正：结构化请求优先判定
        if intent in (DEFAULT_INTENT, INTENT_FREE_DISCUSSION) and _is_structured_request(raw):
            intent = INTENT_STRUCTURED_REQUEST
            logger.info("意图修正: %s -> structured_request (检测到结构化信息)", intent)
        if intent not in (
            INTENT_STRUCTURED_REQUEST,
            INTENT_FREE_DISCUSSION,
            INTENT_CASUAL_CHAT,
            INTENT_DOCUMENT_QUERY,
            INTENT_COMMAND,
        ):
            intent = DEFAULT_INTENT

        base["intent"] = intent
        base["raw_query"] = raw

        # explicit_content_request：规则优先（用户明确说生成/写等），否则用 LLM 输出
        llm_explicit = parsed.get("explicit_content_request")
        if isinstance(llm_explicit, bool):
            base["explicit_content_request"] = llm_explicit
        else:
            base["explicit_content_request"] = False
        if _has_explicit_content_request(raw):
            base["explicit_content_request"] = True
            logger.debug("explicit_content_request=true (规则触发)")

        if intent == INTENT_STRUCTURED_REQUEST:
            base["structured_data"] = _normalize_structured_data(parsed)
        elif intent == INTENT_FREE_DISCUSSION:
            # free_discussion 也需要规则提取自我介绍，供长期记忆持久化
            sd = _normalize_structured_data(parsed)
            if not any(sd.values()):
                intro = _extract_self_intro(raw)
                if intro.get("brand_name") or intro.get("topic"):
                    sd = {**sd, **intro}
            base["structured_data"] = {k: v for k, v in sd.items() if v} if any(sd.values()) else {}
        elif intent == INTENT_CASUAL_CHAT:
            # 闲聊中也保留自我介绍提取（我叫X、我是做X的），供长期记忆持久化
            sd = _normalize_structured_data(parsed)
            if not any(sd.values()):
                intro = _extract_self_intro(raw)
                if intro.get("brand_name") or intro.get("topic"):
                    sd = {**sd, **intro}
            base["structured_data"] = {k: v for k, v in sd.items() if v} if any(sd.values()) else {}
        elif intent == INTENT_DOCUMENT_QUERY:
            # 文档/链接作为参考时，主推广对象仍从对话上下文提取，需保留 parsed 中的 brand/product/topic
            base["structured_data"] = _normalize_structured_data(parsed)
        elif intent == INTENT_COMMAND:
            base["command"] = (parsed.get("command") or "").strip() or cmd

        return base

"""
媒体平台生成规范配置

各媒体的系统提示词、风格要求、生成规范统一在此维护。
新增媒体时在此添加条目，ai_service.generate() 会根据用户表述自动匹配并调用对应规范。

交互逻辑：当用户仅提供产品/目标人群等信息，未明确平台、篇幅时，
先返回澄清问题，引导用户补充后再生成，以提升体验与文案质量。
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class MediaSpec:
    """单个媒体平台的生成规范"""
    key: str
    name: str
    keywords: List[str]
    system_prompt: str
    requirements: str


def build_user_prompt(spec: MediaSpec, analysis_text: str, topic: str, raw_query: str) -> str:
    """根据媒体规范构建 user_prompt"""
    return f"""基于以下分析，生成{spec.name}风格的推广文案：

分析：{analysis_text}

用户需求：话题={topic or '未指定'}；原始表述={raw_query or '未指定'}

要求：
{spec.requirements}
"""


# ========== 媒体规范定义（按匹配优先级排列）==========

BILIBILI_SPEC = MediaSpec(
    key="bilibili",
    name="B站",
    keywords=["B站", "b站", "bilibili", "哔哩哔哩", "小破站"],
    system_prompt=(
        "你是一位熟悉B站社区文化的内容创作者，擅长撰写吸引年轻用户的推广文案。"
        "根据用户的具体表述决定篇幅与结构，完整输出，不截断、不省略。"
    ),
    requirements="""1. 根据用户表述决定篇幅（完整文稿则写完整，简短简介则精炼）
2. 使用B站风格（幽默、有梗、接地气），可适当用流行语、弹幕梗（awsl、yyds、绝绝子等）
3. 突出产品亮点，语言轻松贴近Z世代
4. 直接输出完整文案内容，不要省略、不要截断""",
)

XIAOHONGSHU_SPEC = MediaSpec(
    key="xiaohongshu",
    name="小红书",
    keywords=["小红书", "redbook", "种草"],
    system_prompt=(
        "你是一位熟悉小红书社区的内容创作者，擅长撰写种草文案。"
        "根据用户的具体表述决定篇幅与结构，完整输出，不截断、不省略。"
    ),
    requirements="""1. 根据用户表述决定篇幅（笔记正文则写完整，标题则精炼）
2. 使用小红书风格（真实、种草感、emoji 点缀、口语化）
3. 突出产品亮点和使用体验，营造「我也想要」的氛围
4. 直接输出完整文案内容，不要省略、不要截断""",
)

DOUYIN_SPEC = MediaSpec(
    key="douyin",
    name="抖音",
    keywords=["抖音", "douyin", "短视频"],
    system_prompt=(
        "你是一位熟悉抖音内容风格的内容创作者，擅长撰写短视频脚本/文案。"
        "根据用户的具体表述决定篇幅与结构，完整输出，不截断、不省略。"
    ),
    requirements="""1. 根据用户表述决定篇幅（脚本则写完整，标题/口播则精炼）
2. 使用抖音风格（抓眼球、节奏感、口语化、易口播）
3. 突出产品亮点，适合 15–60 秒短视频呈现
4. 直接输出完整文案内容，不要省略、不要截断""",
)

WEIBO_SPEC = MediaSpec(
    key="weibo",
    name="微博",
    keywords=["微博", "weibo"],
    system_prompt=(
        "你是一位熟悉微博传播特点的内容创作者，擅长撰写微博文案。"
        "根据用户的具体表述决定篇幅与结构，完整输出，不截断、不省略。"
    ),
    requirements="""1. 根据用户表述决定篇幅（长文则写完整，短博则精炼）
2. 使用微博风格（话题感、可转发、易讨论、适当 hashtag）
3. 突出产品亮点，兼顾传播性与品牌调性
4. 直接输出完整文案内容，不要省略、不要截断""",
)

# 通用兜底：用户未指定平台时使用
GENERIC_SPEC = MediaSpec(
    key="generic",
    name="通用",
    keywords=[],
    system_prompt=(
        "你是一位营销文案创作者，擅长撰写各类推广内容。"
        "根据用户的具体表述决定篇幅与结构，完整输出，不截断、不省略。"
    ),
    requirements="""1. 根据用户表述决定篇幅（完整文稿则写完整，简短简介则精炼）
2. 风格贴合用户指定的平台或场景
3. 突出产品亮点，语言清晰有吸引力
4. 直接输出完整文案内容，不要省略、不要截断""",
)

# 按匹配优先级排列（先匹配的优先）
MEDIA_SPECS: List[MediaSpec] = [
    BILIBILI_SPEC,
    XIAOHONGSHU_SPEC,
    DOUYIN_SPEC,
    WEIBO_SPEC,
]


def resolve_media_spec(topic: str = "", raw_query: str = "") -> MediaSpec:
    """
    根据用户话题与原始表述，解析应使用的媒体规范。
    若无法匹配任何平台，返回通用规范。
    """
    combined = (topic or "") + " " + (raw_query or "")
    for spec in MEDIA_SPECS:
        if any(kw in combined for kw in spec.keywords):
            return spec
    return GENERIC_SPEC


def get_spec_by_key(key: str) -> MediaSpec:
    """按 key 获取媒体规范，不存在则返回通用规范"""
    for spec in MEDIA_SPECS:
        if spec.key == key:
            return spec
    return GENERIC_SPEC


# ========== 澄清逻辑：意图感知、按需引导 ==========

def _all_platform_keywords() -> List[str]:
    kw = []
    for spec in MEDIA_SPECS:
        kw.extend(spec.keywords)
    return kw


def has_platform_specified(text: str) -> bool:
    """用户表述中是否已包含发布平台"""
    t = (text or "").strip()
    return any(k in t for k in _all_platform_keywords())


def has_format_specified(text: str) -> bool:
    """用户表述中是否已包含篇幅/格式要求"""
    fmt_kw = ["完整", "长篇", "简短", "简介", "画报", "一句话", "详细", "简要"]
    t = (text or "").strip()
    return any(k in t for k in fmt_kw)


def _looks_like_product_or_campaign(text: str) -> bool:
    """是否像在描述产品/推广需求（而非纯闲聊或命令）"""
    kw = ["推广", "产品", "目标", "人群", "品牌", "营销", "文案", "宣传", "介绍", "卖"]
    t = (text or "").strip()
    return any(k in t for k in kw) and len(t) >= 4


def _wants_content_generation(text: str) -> bool:
    """用户表述是否明确要生成内容（文案、图片、脚本等）"""
    kw = ["生成", "写", "出", "文案", "文稿", "宣传稿", "脚本", "介绍", "画报"]
    t = (text or "").strip()
    return any(k in t for k in kw)


# 涉及营销内容生成的意图，才可能触发澄清
_CLARIFICATION_INTENTS = ("structured_request", "free_discussion", "document_query")


def needs_clarification(
    raw_query: str,
    topic: str,
    product_desc: str,
    brand_name: str = "",
    intent: str = "",
) -> bool:
    """
    是否需要引导用户补充信息。
    - 仅当意图涉及营销内容时考虑澄清
    - 缺基础信息（品牌、产品、主题）时优先引导
    - 明确要生成内容且缺平台/篇幅时再引导
    """
    intent = (intent or "").strip().lower()
    if intent not in _CLARIFICATION_INTENTS:
        return False
    combined = f"{raw_query or ''} {topic or ''} {product_desc or ''} {brand_name or ''}".strip()
    if not combined or not _looks_like_product_or_campaign(combined):
        return False
    has_basic = bool((brand_name or "").strip()) or bool((product_desc or "").strip()) or bool((topic or "").strip())
    # 缺基础信息：引导补充品牌/产品/主题
    if not has_basic:
        return True
    # 有基础信息：仅当用户明确要生成内容且缺平台/篇幅时引导
    if not _wants_content_generation(combined):
        return False
    has_platform = has_platform_specified(combined)
    has_format = has_format_specified(combined)
    return not (has_platform or has_format)


def get_clarification_response(
    product_summary: str = "",
    brand_name: str = "",
    product_desc: str = "",
    topic: str = "",
) -> str:
    """根据缺失项动态生成引导文案"""
    summary = (product_summary or product_desc or brand_name or "您的产品").strip()
    has_basic = bool((brand_name or "").strip()) or bool((product_desc or "").strip()) or bool((topic or "").strip())
    platform_names = "、".join(s.name for s in MEDIA_SPECS)
    parts = []
    if not has_basic:
        parts.append("好的，我来帮您！为了更好地开展营销创作，请补充：品牌、产品描述或推广主题（如「推广华为手机，目标18-35岁人群」）。")
    else:
        parts.append(f"好的，已了解：{summary}。")
        combined = f"{brand_name or ''} {product_desc or ''} {topic or ''}".strip()
        has_platform = has_platform_specified(combined)
        has_format = has_format_specified(combined)
        if not has_platform:
            parts.append(f"**发布平台**：{platform_names}，或其他？")
        if not has_format:
            parts.append("**篇幅要求**：完整文稿 / 简短简介 / 画报介绍？")
    if len(parts) == 1 and not has_basic:
        return parts[0]
    return "\n".join(parts) + "\n\n确认后我将为您生成相应内容。"

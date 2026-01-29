import json
import logging
import os
import random
from typing import Any, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from models.request import ContentRequest

from cache.smart_cache import SmartCache, build_analyze_cache_key

logger = logging.getLogger(__name__)

# 分析缓存 TTL 基准（秒）与随机偏差，避免缓存雪崩
CACHE_TTL_BASE = 1800
CACHE_TTL_JITTER = 300

# analyze 解析失败时的默认返回值，保证工作流继续
DEFAULT_ANALYSIS_DICT = {
    "semantic_score": 0,
    "angle": "暂无推荐切入点",
    "reason": "分析结果解析失败，请重试。",
}


class SimpleAIService:
    """AI 服务类，使用 Deepseek 模型生成内容"""

    def __init__(self, cache: Optional[SmartCache] = None) -> None:
        """
        初始化 ChatOpenAI 客户端（最新稳定版 API），用于分析、生成与评估（统一 DeepSeek）。
        可选注入 SmartCache，analyze 会先查缓存再调模型。
        """
        self.client = ChatOpenAI(
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key=os.getenv("DEEPSEEK_API_KEY", "sk-cef65d7e728d43d79a4a23d642faa6d0"),
            temperature=0.7,
        )
        self.cache = cache

    async def _real_analyze_call(
        self,
        request: ContentRequest,
        preference_context: str | None,
    ) -> dict[str, Any]:
        """真实的分析调用逻辑（调模型、解析 JSON），供 analyze 或缓存未命中时使用。"""
        system_prompt = (
            "你是一位资深营销顾问，请综合用户的历史画像和过往交互偏好进行本次分析，"
            "确保建议的连贯性和个性化。"
        )

        user_prompt = f"""请根据以下信息，分析品牌与热点话题的关联度，并给出推荐切入点和理由。

【本次请求】
品牌名称：{request.brand_name}
产品描述：{request.product_desc}
热点话题：{request.topic}
"""
        if preference_context:
            user_prompt += f"""
【用户长期记忆 / 历史画像与过往交互偏好】
{preference_context}
"""
        user_prompt += """

请只输出一个 JSON 对象，不要有任何其他文本、说明或 markdown 标题。
必须用三个反引号包裹，格式为：```json
{{ ... }}
```

JSON 必须至少包含以下字段（类型与含义不可变）：
- semantic_score：整数，0-100，表示品牌与热点的语义关联度
- angle：字符串，推荐的营销切入点或创意角度
- reason：字符串，简要分析理由（可结合用户历史偏好说明）

只输出 JSON，不要有任何其他文本。"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = await self.client.ainvoke(messages)
        raw = (response.content or "").strip()

        for prefix in ("```json", "```"):
            if raw.startswith(prefix):
                raw = raw[len(prefix) :].strip()
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")].strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("analyze JSON 解析失败: %s\nraw=%s", e, raw[:500])
            return DEFAULT_ANALYSIS_DICT.copy()

        if not isinstance(data, dict):
            return DEFAULT_ANALYSIS_DICT.copy()

        return {
            "semantic_score": data.get("semantic_score", 0),
            "angle": data.get("angle", ""),
            "reason": data.get("reason", ""),
        }

    async def analyze(
        self,
        request: ContentRequest,
        preference_context: str | None = None,
        context_fingerprint: dict | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """
        分析品牌和热点关联度；综合用户历史画像与过往交互偏好，输出结构化 JSON。
        若注入了 SmartCache，则先按「请求四元组 + 上下文指纹」生成键查缓存，未命中再调 _real_analyze_call。
        上下文指纹含用户标签与近三次交互主题集合，兼顾命中率与个性化、新鲜度（TTL 限制）。

        Returns:
            (分析结果字典, 是否命中缓存)
        """
        key = build_analyze_cache_key(
            user_id=request.user_id or "",
            brand_name=request.brand_name or "",
            product_desc=request.product_desc or "",
            topic=request.topic or "",
            context_fingerprint=context_fingerprint,
        )

        if self.cache is not None:
            ttl = CACHE_TTL_BASE + random.randint(-CACHE_TTL_JITTER, CACHE_TTL_JITTER)
            result, cache_hit = await self.cache.get_or_set(
                key,
                lambda: self._real_analyze_call(request, preference_context),
                ttl=ttl,
            )
            logger.info("analyze 缓存 %s key=%s", "命中" if cache_hit else "未命中", key)
            return result, cache_hit
        result = await self._real_analyze_call(request, preference_context)
        return result, False

    async def evaluate_content(self, content: str, context: dict) -> dict[str, Any]:
        """
        对待评估文本从四维度打分（与品牌目标一致性、创意度、语言风险、平台风格契合度），
        并给出简要改进意见。使用与 analyze/generate 相同的 self.client（DeepSeek）。
        强制只输出固定 JSON 格式；解析失败或 AI 调用异常时返回预设默认字典，不中断工作流。

        Args:
            content: 待评估文本（如生成的推广文案）
            context: 分析上下文，至少包含 brand_name、topic 等（本次请求信息）

        Returns:
            至少包含 scores（各维度 1-10 分）、overall（综合分）、suggestions（改进意见）的字典；
            兼容 overall_score（整数）供 need_revision 判断。
        """
        default = {
            "scores": {"consistency": 0, "creativity": 0, "safety": 0, "platform_fit": 0},
            "overall": 0.0,
            "suggestions": "评估解析失败或 AI 调用异常，未生成建议。",
            "overall_score": 0,
            "evaluation_failed": True,
        }

        try:
            brand_name = context.get("brand_name", "")
            topic = context.get("topic", "")
            analysis_summary = context.get("analysis", "")

            system_prompt = (
                "你是一位营销文案评审，对推广内容做多维度打分并给出改进建议。"
                "你必须只输出一个纯 JSON 对象，不要有任何其他文字、说明或 markdown。"
                "只输出 JSON，这是稳定性的生命线。"
            )
            user_prompt = f"""请对以下推广内容从四个维度打分（每项 1-10 分），并给出综合分与简要改进意见。

【待评估内容】
{content[:2000]}

【本次请求 / 分析上下文】
品牌名称：{brand_name}
热点/主题：{topic}
分析摘要：{analysis_summary or "无"}

【四个维度】
1. consistency（与品牌目标的一致性）：是否紧扣品牌与主题，传达清晰
2. creativity（创意度）：是否有新意、记忆点
3. safety（语言风险/合规）：是否合规、无争议与翻车风险（10 为最安全）
4. platform_fit（平台风格契合度）：是否符合 B 站等目标平台的调性与用户习惯

【输出格式】你必须只输出一个纯 JSON 对象，不要有任何其他文本。
只输出 JSON。固定格式示例：
{{"scores": {{"consistency": 8, "creativity": 9, "safety": 9, "platform_fit": 8}}, "overall": 8.5, "suggestions": "一两句改进建议"}}

- scores：对象，必须包含 consistency、creativity、safety、platform_fit，均为整数 1-10
- overall：综合分，数字，可保留一位小数
- suggestions：字符串，简要改进意见

只输出 JSON，不要有任何其他文字、标点或说明。"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            response = await self.client.ainvoke(messages)
            raw = (response.content or "").strip()
            for prefix in ("```json", "```"):
                if raw.startswith(prefix):
                    raw = raw[len(prefix) :].strip()
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")].strip()

            data = json.loads(raw)
            if not isinstance(data, dict):
                return default

            scores = data.get("scores") or {}
            overall = data.get("overall", 0)
            try:
                overall = float(overall)
            except (TypeError, ValueError):
                overall = 0.0
            overall = max(0.0, min(10.0, overall))
            overall_score = int(round(overall))

            return {
                "scores": {
                    "consistency": scores.get("consistency", 0),
                    "creativity": scores.get("creativity", 0),
                    "safety": scores.get("safety", 0),
                    "platform_fit": scores.get("platform_fit", 0),
                },
                "overall": round(overall, 1),
                "suggestions": data.get("suggestions", "") or default["suggestions"],
                "overall_score": overall_score,
            }
        except json.JSONDecodeError as e:
            logger.warning("evaluate_content JSON 解析失败: %s\nraw=%s", e, raw[:300])
            return default
        except Exception as e:
            logger.exception("evaluate_content AI 调用或处理异常: %s", e)
            return default

    async def generate(self, analysis: str | dict[str, Any]) -> str:
        """
        生成B站风格的推广文案。

        Args:
            analysis: 分析结果，可为字符串或 analyze() 返回的结构化字典（含 angle、reason、semantic_score）

        Returns:
            B站风格的推广文案
        """
        if isinstance(analysis, dict):
            analysis_text = (
                f"关联度得分：{analysis.get('semantic_score', 0)}；"
                f"推荐切入点：{analysis.get('angle', '')}；"
                f"分析理由：{analysis.get('reason', '')}"
            )
        else:
            analysis_text = analysis or ""

        system_prompt = "你是一位熟悉B站社区文化的内容创作者，擅长撰写吸引年轻用户的推广文案。"

        user_prompt = f"""基于以下分析，生成一段B站风格的推广文案：

分析：{analysis_text}

要求：
1. 使用B站常见的文案风格（幽默、有梗、接地气）
2. 可适当使用B站流行语、弹幕梗（如"awsl"、"yyds"、"绝绝子"、"笑死"等）
3. 语言轻松有趣，贴近Z世代用户
4. 长度控制在 200-300 字左右
5. 突出产品亮点和与热点的关联
6. 可以使用适量 emoji 表情符号增加趣味性
7. 适合在B站动态、评论区或视频简介中发布"""

        # 直接使用 ChatOpenAI 实例作为可调用对象（最新 API）
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        # 异步调用
        response = await self.client.ainvoke(messages)
        # 通过 .content 属性获取生成的文本
        return response.content

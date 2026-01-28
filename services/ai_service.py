import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from models.request import ContentRequest


class SimpleAIService:
    """AI 服务类，使用 Deepseek 模型生成内容"""

    def __init__(self) -> None:
        """
        初始化 ChatOpenAI 客户端（最新稳定版 API）。

        使用 model 参数（而非已废弃的 model_name），保留 Deepseek 模型配置。
        """
        self.client = ChatOpenAI(
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key=os.getenv("DEEPSEEK_API_KEY", "sk-cef65d7e728d43d79a4a23d642faa6d0"),
            temperature=0.7,
        )

    async def analyze(
        self,
        request: ContentRequest,
        preference_context: str | None = None,
    ) -> str:
        """
        分析品牌和热点关联度；可传入用户偏好上下文，实现基于记忆的个性化分析。

        Args:
            request: ContentRequest 对象，包含品牌名称、产品描述和主题
            preference_context: 用户历史偏好等上下文（如 preferred_style），可选

        Returns:
            分析品牌和热点关联度的一句话
        """
        # 使用 f-string 构造提示词（最新最佳实践）
        system_prompt = "你是一位资深的品牌营销专家，擅长分析品牌与热点话题之间的关联度。"

        user_prompt = f"""请分析以下品牌与热点话题的关联度，用一句话概括：

品牌名称：{request.brand_name}
产品描述：{request.product_desc}
热点话题：{request.topic}
"""
        if preference_context:
            user_prompt += f"""
用户历史偏好/上下文（请在分析时参考）：
{preference_context}
"""
        user_prompt += """
请用一句话分析这个品牌与热点话题的关联度，说明它们之间的契合点。若提供了用户偏好，可在分析中适当体现个性化视角。"""

        # 直接使用 ChatOpenAI 实例作为可调用对象（最新 API）
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        # 异步调用，返回 AIMessage 对象
        response = await self.client.ainvoke(messages)
        # 通过 .content 属性提取文本
        return response.content

    async def generate(self, analysis: str) -> str:
        """
        生成B站风格的推广文案。

        Args:
            analysis: 分析结果

        Returns:
            B站风格的推广文案
        """
        # 使用 f-string 构造提示词（最新最佳实践）
        system_prompt = "你是一位熟悉B站社区文化的内容创作者，擅长撰写吸引年轻用户的推广文案。"

        user_prompt = f"""基于以下分析，生成一段B站风格的推广文案：

分析：{analysis}

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

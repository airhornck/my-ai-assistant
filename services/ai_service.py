import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from models.request import ContentRequest


class SimpleAIService:
    """简单的 AI 服务类，使用 Deepseek 模型"""
    
    def __init__(self):
        """初始化 ChatOpenAI 客户端，使用 Deepseek 模型"""
        self.client = ChatOpenAI(
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key=os.getenv("DEEPSEEK_API_KEY", "sk-cef65d7e728d43d79a4a23d642faa6d0"),
            temperature=0.7,
        )
    
    async def analyze(self, request: ContentRequest) -> str:
        """
        分析品牌和热点关联度
        
        Args:
            request: ContentRequest 对象，包含品牌名称、产品描述和主题
            
        Returns:
            分析品牌和热点关联度的一句话
        """
        prompt = f"""请分析以下品牌与热点话题的关联度，用一句话概括：

品牌名称：{request.brand_name}
产品描述：{request.product_desc}
热点话题：{request.topic}

请用一句话分析这个品牌与热点话题的关联度，说明它们之间的契合点。"""
        
        messages = [HumanMessage(content=prompt)]
        response = await self.client.ainvoke(messages)
        return response.content
    
    async def generate(self, analysis: str) -> str:
        """
        生成小红书风格的推广文案
        
        Args:
            analysis: 分析结果
            
        Returns:
            小红书风格的推广文案
        """
        prompt = f"""基于以下分析，生成一段小红书风格的推广文案：

分析：{analysis}

要求：
1. 使用小红书常见的文案风格（亲切、真实、有感染力）
2. 包含 emoji 表情符号
3. 语言轻松活泼，贴近年轻用户
4. 长度控制在 200-300 字左右
5. 突出产品亮点和与热点的关联"""
        
        messages = [HumanMessage(content=prompt)]
        response = await self.client.ainvoke(messages)
        return response.content

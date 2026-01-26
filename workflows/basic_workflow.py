from typing import TypedDict, Any
import json
from langgraph.graph import StateGraph, END
from services.ai_service import SimpleAIService
from models.request import ContentRequest


class State(TypedDict):
    """工作流状态定义"""
    user_input: str
    analysis: str
    content: str


# 创建 AI 服务实例
ai_service = SimpleAIService()


async def analyze_node(state: State) -> State:
    """分析节点：分析用户输入"""
    # 将 user_input 解析为 ContentRequest
    try:
        # 假设 user_input 是 JSON 字符串
        data = json.loads(state["user_input"])
        request = ContentRequest(**data)
    except (json.JSONDecodeError, TypeError):
        # 如果不是 JSON，尝试从字符串构造（这里需要根据实际需求调整）
        # 暂时使用默认值
        request = ContentRequest(
            brand_name="",
            product_desc=state["user_input"],
            topic=""
        )
    
    # 使用 AI 服务进行分析
    analysis_result = await ai_service.analyze(request)
    
    return {
        **state,
        "analysis": analysis_result
    }


async def generate_node(state: State) -> State:
    """生成节点：基于分析结果生成内容"""
    generated_content = await ai_service.generate(state["analysis"])
    
    return {
        **state,
        "content": generated_content
    }


def format_node(state: State) -> State:
    """格式化节点：格式化生成的内容"""
    # 简单的格式化，可以添加更多格式化逻辑
    formatted_content = f"📝 推广文案：\n\n{state['content']}\n\n✨ 基于分析：{state['analysis']}"
    
    return {
        **state,
        "content": formatted_content
    }


def create_workflow() -> Any:
    """创建工作流"""
    # 创建状态图
    workflow = StateGraph(State)
    
    # 添加节点
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("format", format_node)
    
    # 设置入口点
    workflow.set_entry_point("analyze")
    
    # 设置线性边
    workflow.add_edge("analyze", "generate")
    workflow.add_edge("generate", "format")
    workflow.add_edge("format", END)
    
    # 编译并返回图
    return workflow.compile()

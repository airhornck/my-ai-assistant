from typing import TypedDict, Any
import json
from langgraph.graph import StateGraph, END
from services.ai_service import SimpleAIService
from models.request import ContentRequest
# 移除 SessionManager 的全局导入和初始化

class State(TypedDict):
    """
    工作流状态定义 - 使用 TypedDict 确保类型安全。
    """
    user_input: str
    analysis: str
    content: str
    session_id: str
    user_id: str

# 只创建 AI 服务实例
ai_service = SimpleAIService()

def _preference_context_from_session(session_data: dict) -> str:
    """从会话数据中提取用户偏好，拼接为上下文字符串。"""
    parts = []
    initial = session_data.get("initial_data") or {}
    profile = initial.get("user_profile") or {}
    if profile.get("preferred_style"):
        parts.append(f"偏好风格：{profile['preferred_style']}")
    if profile.get("industry"):
        parts.append(f"行业：{profile['industry']}")
    if profile.get("brand_name"):
        parts.append(f"品牌：{profile['brand_name']}")
    return "\n".join(parts) if parts else ""

async def analyze_node(state: State) -> State:
    """
    分析节点：分析用户输入；基于 session 中的用户偏好做个性化分析。
    """
    # 将 user_input 解析为 ContentRequest
    try:
        data = json.loads(state["user_input"])
        request = ContentRequest(**data)
    except (json.JSONDecodeError, TypeError):
        request = ContentRequest(
            user_id=state.get("user_id", ""),
            brand_name="",
            product_desc=state["user_input"],
            topic="",
        )

    # 初始化 preference_context
    preference_context = ""

    # 返回更新后的状态字典
    return {
        **state,
        "analysis": f"分析完成（本次未使用历史偏好）。请求品牌：{request.brand_name}"
    }

async def generate_node(state: State) -> State:
    """
    生成节点：基于分析结果生成内容。
    """
    generated_content = await ai_service.generate(state["analysis"])
    
    # 返回更新后的状态字典
    return {
        **state,
        "content": generated_content
    }

def format_node(state: State) -> State:
    """
    格式化节点：格式化生成的内容。
    """
    formatted_content = f"📝 推广文案：\n\n{state['content']}\n\n✨ 基于分析：{state['analysis']}"
    return {
        **state,
        "content": formatted_content
    }

def create_workflow() -> Any:
    """
    创建工作流图。
    """
    workflow = StateGraph(State)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("format", format_node)
    workflow.set_entry_point("analyze")
    workflow.add_edge("analyze", "generate")
    workflow.add_edge("generate", "format")
    workflow.add_edge("format", END)
    return workflow.compile()
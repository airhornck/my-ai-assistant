from typing import List, Optional

from pydantic import BaseModel, Field


class ContentRequest(BaseModel):
    """内容生成请求体模型"""
    
    user_id: str = Field(
        ...,
        description="用户唯一标识",
        example="user_12345"
    )
    
    # 删除 session_id 字段，由服务器自动创建和管理
    # session_id: Optional[str] = Field(...)
    
    brand_name: str = Field(
        ...,
        description="品牌名称",
        example="Apple"
    )
    
    product_desc: str = Field(
        ...,
        description="产品描述",
        example="最新款智能手机，配备强大的A17芯片和先进的摄像头系统"
    )
    
    topic: str = Field(
        ...,
        description="主题",
        example="产品推广"
    )
    
    tags: Optional[List[str]] = Field(
        default=None,
        description="用户提供的兴趣标签（非必填）。若提供则覆盖系统根据历史生成的标签，并记入档案供下次使用；若不提供则使用系统根据历史生成的标签；首次无输入且无历史时为空",
        example=["科技数码", "简洁文案"]
    )


class RawAnalyzeRequest(BaseModel):
    """原始输入请求体：用于 /api/v1/analyze-deep/raw，经 InputProcessor 意图识别与标准化后进入元工作流。"""

    user_id: str = Field(
        ...,
        description="用户唯一标识",
        example="user_12345",
    )
    raw_input: str = Field(
        ...,
        min_length=1,
        description="用户原始输入（自然语言或命令，如 /new_chat）",
        example="我想做一个针对Z世代的咖啡品牌推广",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="可选会话 ID；若提供且有效则沿用该会话，否则创建新会话",
        example="550e8400-e29b-41d4-a716-446655440000",
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="用户提供的兴趣标签（非必填）",
        example=["科技数码", "简洁文案"],
    )


class NewChatRequest(BaseModel):
    """新建对话链请求体：用于 POST /api/v1/chat/new，显式创建新对话链并返回 thread_id 与 session_id。"""

    user_id: str = Field(
        ...,
        description="用户唯一标识",
        example="user_12345",
    )


class FeedbackRequest(BaseModel):
    """反馈接口请求体"""

    session_id: str = Field(
        ...,
        min_length=1,
        description="会话 ID",
        example="550e8400-e29b-41d4-a716-446655440000",
    )
    rating: int = Field(
        ...,
        ge=1,
        le=5,
        description="用户评分 1–5",
        example=4,
    )
    comment: str = Field(
        default="",
        description="用户文字反馈",
        example="文案很接地气",
    )


class ChatResumeRequest(BaseModel):
    """人工介入恢复请求体：用于 POST /api/v1/chat/resume，在评估后选择是否修订。"""
    session_id: str = Field(..., description="会话 ID（与中断时的 thread_id 一致）")
    human_decision: str = Field(..., description="是否修订：revise | skip")


class FrontendChatRequest(BaseModel):
    """
    前端聊天统一接口请求体：用于 POST /api/v1/frontend/chat。
    系统根据意图自动路由：【闲聊】走快捷回复；【创作】走策略脑+分析脑+生成脑。
    """

    message: str = Field(
        ...,
        min_length=1,
        description="用户消息内容（自然语言或命令）",
        example="我想推广一款新的降噪耳机",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="会话 ID；若为空或过期则自动创建新会话",
        example="550e8400-e29b-41d4-a716-446655440000",
    )
    user_id: str = Field(
        ...,
        description="用户唯一标识",
        example="user_12345",
    )
    mode: Optional[str] = Field(
        default=None,
        description="已废弃，忽略。系统按意图自动路由。",
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="用户提供的兴趣标签（仅 deep 模式使用）",
        example=["科技", "年轻人"],
    )
    history: Optional[List[dict]] = Field(
        default=None,
        description="对话历史，格式 [{\"role\": \"user\"|\"assistant\", \"content\": \"...\"}]，用于上下文记忆",
    )
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
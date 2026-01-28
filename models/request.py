from pydantic import BaseModel, Field
from typing import Optional

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
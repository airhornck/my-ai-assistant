from fastapi import FastAPI
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import json
from models.request import ContentRequest
from workflows.basic_workflow import create_workflow
from services.ai_service import SimpleAIService
from services.session_service import SessionService


# 全局变量存储 AI 服务、工作流和会话服务
ai_service = None
workflow = None
session_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化，关闭时清理"""
    # 启动时初始化
    global ai_service, workflow, session_service
    ai_service = SimpleAIService()
    workflow = create_workflow()
    session_service = SessionService()
    yield
    # 关闭时清理（如果需要）


# 创建 FastAPI 应用
app = FastAPI(title="AI 助手 API",
description="基于 LangGraph 的内容生成服务",
version="1.0.0",
lifespan=lifespan
)


@app.post("/api/v1/create")
async def create_content(request: ContentRequest) -> JSONResponse:
    """
    创建内容接口
    
    Args:
        request: ContentRequest 对象，包含用户ID、会话ID、品牌名称、产品描述和主题
        
    Returns:
        生成的内容和会话ID
    """
    try:
        # 获取 user_id 和 session_id
        user_id = request.user_id
        session_id = request.session_id
        
        # 构建当前请求数据
        current_request_data = {
            "brand_name": request.brand_name,
            "product_desc": request.product_desc,
            "topic": request.topic
        }
        
        # 处理会话逻辑
        if not session_id:
            # 如果 session_id 为空，创建新会话
            session_id = await session_service.create_session(
                user_id=user_id,
                initial_data=current_request_data
            )
            # 新会话，历史数据为空
            historical_data = {}
        else:
            # 如果 session_id 不为空，获取历史会话数据
            session_data = await session_service.get_session(session_id)
            if session_data:
                # 获取历史数据（从 initial_data 中获取）
                historical_data = session_data.get("initial_data", {})
            else:
                # 如果会话不存在，创建新会话
                session_id = await session_service.create_session(
                    user_id=user_id,
                    initial_data=current_request_data
                )
                historical_data = {}
        
        # 合并当前请求数据和历史会话数据
        merged_data = {
            **historical_data,
            **current_request_data  # 当前请求数据会覆盖历史数据中的相同字段
        }
        
        # 将合并后的数据转换为 JSON 字符串，作为工作流的 user_input
        user_input = json.dumps(merged_data, ensure_ascii=False)
        
        # 初始化工作流状态
        initial_state = {
            "user_input": user_input,
            "analysis": "",
            "content": ""
        }
        
        # 执行工作流
        result = await workflow.ainvoke(initial_state)
        
        # 返回生成的内容，必须包含 session_id
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "session_id": session_id,
                    "content": result["content"],
                    "analysis": result["analysis"]
                }
            },
            status_code=200
        )
    except Exception as e:
        return JSONResponse(
            content={
                "success": False,
                "error": str(e)
            },
            status_code=500
        )


@app.get("/")
async def root():
    """根路径"""
    return {"message": "AI 助手 API 服务运行中"}


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}

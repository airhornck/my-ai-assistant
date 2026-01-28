import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine

from database import (
    InteractionHistory,
    engine,
    get_db,
    get_or_create_user_profile,
    create_tables,
)
from memory.session_manager import SessionManager
from models.request import ContentRequest
from services.ai_service import SimpleAIService
from workflows.basic_workflow import create_workflow


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 全局变量存储服务实例
workflow = None
session_manager: SessionManager | None = None
db_engine: AsyncEngine = engine
ai_service: SimpleAIService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器（兼容 fastapi>=0.110.0）。
    
    管理应用启动和关闭时的资源初始化与清理：
    - 启动：初始化数据库、SessionManager、AI服务和工作流
    - 关闭：关闭所有连接
    """
    global workflow, session_manager, db_engine, ai_service

    # 启动阶段
    try:
        # 1. 初始化异步数据库引擎并创建表
        logger.info("正在初始化数据库...")
        await create_tables(db_engine)
        logger.info("数据库表初始化完成")

        # 2. 初始化 AI 服务
        logger.info("正在初始化 AI 服务...")
        ai_service = SimpleAIService()
        logger.info("AI 服务初始化完成")

        # 3. 初始化 SessionManager（异步 Redis 客户端）
        logger.info("正在初始化 SessionManager...")
        session_manager = SessionManager()
        logger.info("SessionManager 初始化完成")

        # 4. 初始化工作流图
        logger.info("正在初始化工作流...")
        workflow = create_workflow()
        logger.info("工作流初始化完成")

        logger.info("✅ 应用启动完成，所有服务已就绪")
    except Exception as e:
        logger.error(f"❌ 应用启动失败: {e}", exc_info=True)
        raise

    yield

    # 关闭阶段：清理资源
    logger.info("正在关闭应用...")

    # 关闭 SessionManager（异步 Redis 连接）
    if session_manager:
        try:
            await session_manager.close()
            logger.info("SessionManager 连接已关闭")
        except Exception as e:
            logger.error(f"关闭 SessionManager 时出错: {e}")

    # 关闭数据库引擎（asyncpg 连接池）
    if db_engine:
        try:
            await db_engine.dispose()
            logger.info("数据库引擎已关闭")
        except Exception as e:
            logger.error(f"关闭数据库引擎时出错: {e}")

    logger.info("应用关闭完成")


# 创建 FastAPI 应用（使用 lifespan 上下文管理器）
app = FastAPI(
    title="AI 助手 API",
    description="基于 LangGraph 与记忆系统的内容生成服务",
    version="1.0.0",
    lifespan=lifespan,
)


async def get_session_manager() -> AsyncGenerator[SessionManager, None]:
    """
    异步依赖项：提供 SessionManager 实例。
    
    Yields:
        SessionManager: 会话管理器实例
        
    Raises:
        RuntimeError: SessionManager 未初始化时
    """
    if session_manager is None:
        raise RuntimeError("SessionManager 未初始化")
    yield session_manager


async def get_ai_service() -> AsyncGenerator[SimpleAIService, None]:
    """
    异步依赖项：提供 AI 服务实例。
    """
    if ai_service is None:
        raise RuntimeError("AI 服务未初始化")
    yield ai_service


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    全局异常处理器：捕获所有未处理的异常，返回格式统一的错误响应。
    
    避免敏感信息泄露，仅返回通用错误消息。
    """
    logger.error(f"未处理的异常: {exc}", exc_info=True)

    return JSONResponse(
        content={
            "success": False,
            "error": "服务器内部错误，请稍后重试",
        },
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """请求验证异常处理器"""
    return JSONResponse(
        content={
            "success": False,
            "error": "请求参数验证失败",
            "details": exc.errors(),
        },
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


@app.post("/api/v1/create")
async def create_content(
    request: ContentRequest,
    db: AsyncSession = Depends(get_db),
    sm: SessionManager = Depends(get_session_manager),
    ai: SimpleAIService = Depends(get_ai_service),
) -> JSONResponse:
    """
    创建内容接口（完全异步模式）。
    
    核心流程：
    1. 根据 user_id 获取或创建用户档案
    2. 创建新会话，并将用户信息存入会话
    3. 执行工作流，生成内容
    4. 保存本次交互历史到数据库
    
    注意：session_id 由后端自动生成，不在请求体中接收。
    """
    try:
        user_id = request.user_id

        # 1. 根据 user_id 获取或创建用户档案（异步）
        profile = await get_or_create_user_profile(db, user_id)
        logger.info(f"获取/创建用户档案完成，user_id: {user_id}")

        # 2. 创建新会话，并将用户档案信息存入会话（异步）
        # 构建会话的初始数据
        session_data = {
            "user_profile": {
                "user_id": profile.user_id,
                "brand_name": profile.brand_name,
                "industry": profile.industry,
                "preferred_style": profile.preferred_style,
            },
            "request_info": {
                "brand_name": request.brand_name,
                "product_desc": request.product_desc,
                "topic": request.topic,
            }
        }
        
        # 创建新会话（session_id 由 SessionManager 自动生成）
        session_id = await sm.create_session(
            user_id=user_id,
            initial_data=session_data
        )
        logger.info(f"创建新会话完成，session_id: {session_id}")

        # 3. 执行工作流，将 session_id、user_id 和用户偏好传入初始状态
        # 构建工作流的输入状态
        initial_state = {
            "user_input": json.dumps({
                "user_id": user_id,
                "brand_name": request.brand_name,
                "product_desc": request.product_desc,
                "topic": request.topic,
            }, ensure_ascii=False),
            "analysis": "",
            "content": "",
            "session_id": session_id,  # 使用后端生成的 session_id
            "user_id": user_id,
        }
        
        # 执行工作流
        logger.info(f"开始执行工作流，session_id: {session_id}")
        result = await workflow.ainvoke(initial_state)
        logger.info(f"工作流执行完成，session_id: {session_id}")

        # 4. 将本次交互的输入、输出保存到 InteractionHistory（异步）
        history = InteractionHistory(
            user_id=user_id,
            session_id=session_id,
            user_input=json.dumps({
                "brand_name": request.brand_name,
                "product_desc": request.product_desc,
                "topic": request.topic,
            }, ensure_ascii=False),
            ai_output=result["content"],
        )
        db.add(history)
        await db.commit()
        logger.info(f"交互历史已保存，session_id: {session_id}")

        # 5. 返回成功响应
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "session_id": session_id,
                    "user_id": user_id,
                    "content": result["content"],
                    "analysis": result["analysis"],
                    "timestamp": history.created_at.isoformat() if history.created_at else None,
                },
            },
            status_code=status.HTTP_200_OK,
        )
        
    except Exception as e:
        # 发生异常时回滚数据库事务
        try:
            await db.rollback()
        except Exception:
            pass
        
        logger.error(f"创建内容时出错: {e}", exc_info=True)
        # 异常会被全局异常处理器捕获
        raise


@app.get("/")
async def root() -> dict:
    """根路径，服务状态检查"""
    status_info = {
        "service": "AI 助手 API",
        "status": "运行中",
        "version": "1.0.0",
        "endpoints": {
            "docs": "/docs",
            "health": "/health",
            "create_content": "/api/v1/create (POST)"
        }
    }
    
    # 检查关键服务状态
    if workflow is None:
        status_info["status"] = "工作流未初始化"
    if session_manager is None:
        status_info["status"] = "会话管理器未初始化"
    
    return status_info


@app.get("/health")
async def health_check() -> dict:
    """健康检查端点，用于 Docker 健康检查"""
    health_status = {
        "status": "healthy",
        "services": {}
    }
    
    # 检查数据库连接
    try:
        async with db_engine.connect() as conn:
            await conn.execute("SELECT 1")
            health_status["services"]["database"] = "healthy"
    except Exception as e:
        health_status["services"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "unhealthy"
    
    # 检查 Redis 连接（通过 SessionManager）
    if session_manager:
        try:
            # 尝试一个简单的 Redis 命令
            import redis.asyncio as redis
            if hasattr(session_manager, '_redis'):
                await session_manager._redis.ping()
                health_status["services"]["redis"] = "healthy"
            else:
                health_status["services"]["redis"] = "unhealthy: Redis client not found"
                health_status["status"] = "unhealthy"
        except Exception as e:
            health_status["services"]["redis"] = f"unhealthy: {str(e)}"
            health_status["status"] = "unhealthy"
    
    # 检查工作流
    health_status["services"]["workflow"] = "healthy" if workflow is not None else "unhealthy: not initialized"
    if workflow is None:
        health_status["status"] = "unhealthy"
    
    # 检查 AI 服务
    health_status["services"]["ai_service"] = "healthy" if ai_service is not None else "unhealthy: not initialized"
    if ai_service is None:
        health_status["status"] = "unhealthy"
    
    return health_status


@app.get("/api/v1/session/{session_id}")
async def get_session_info(
    session_id: str,
    sm: SessionManager = Depends(get_session_manager)
) -> JSONResponse:
    """
    获取会话信息（用于调试和验证记忆系统）。
    
    返回指定 session_id 的会话数据，验证记忆系统是否正常工作。
    """
    try:
        session_data = await sm.get_session(session_id)
        
        if session_data is None:
            return JSONResponse(
                content={
                    "success": False,
                    "error": f"会话不存在或已过期: {session_id}",
                },
                status_code=status.HTTP_404_NOT_FOUND,
            )
        
        return JSONResponse(
            content={
                "success": True,
                "data": session_data,
            },
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"获取会话信息时出错: {e}", exc_info=True)
        raise
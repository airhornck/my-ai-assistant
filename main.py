import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from prometheus_client import Counter, Histogram
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine
from starlette.middleware.base import BaseHTTPMiddleware

from database import (
    AsyncSessionLocal,
    InteractionHistory,
    engine,
    get_db,
    get_or_create_user_profile,
    create_tables,
)
from memory.session_manager import SessionManager
from models.request import ContentRequest, FeedbackRequest
from services.ai_service import SimpleAIService
from services.feedback_service import FeedbackService
from cache.smart_cache import SmartCache
from workflows.basic_workflow import create_workflow


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus 指标（单进程模式；多进程时需改用 multiprocess 模式）
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency in seconds",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# 全局变量存储服务实例
workflow = None
session_manager: SessionManager | None = None
db_engine: AsyncEngine = engine
ai_service: SimpleAIService | None = None
feedback_service: FeedbackService | None = None
smart_cache: SmartCache | None = None

# 启动重试：Docker 使用 depends_on service_started 时 DB/Redis 可能尚未就绪
_STARTUP_RETRY_SECONDS = 30
_STARTUP_RETRY_INTERVAL = 2


async def _retry_until_ready(step_name: str, coro_factory):
    """对异步操作重试直到成功或超时（用于 DB/Redis 启动等待）。"""
    deadline = time.perf_counter() + _STARTUP_RETRY_SECONDS
    attempt = 0
    while True:
        attempt += 1
        try:
            await coro_factory()
            return
        except Exception as e:
            if time.perf_counter() >= deadline:
                logger.error("%s 在 %ds 内重试 %d 次后仍失败: %s", step_name, _STARTUP_RETRY_SECONDS, attempt, e)
                raise
            logger.warning("%s 第 %d 次失败，%s 秒后重试: %s", step_name, attempt, _STARTUP_RETRY_INTERVAL, e)
            await asyncio.sleep(_STARTUP_RETRY_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器（兼容 fastapi>=0.110.0）。
    
    管理应用启动和关闭时的资源初始化与清理：
    - 启动：初始化数据库、缓存、AI服务、SessionManager和工作流
    - 关闭：关闭所有连接
    注：周期性更新用户标签由独立 memory-optimizer 容器负责（docker-compose.prod.yml），
    单容器/本地开发时如需更新标签可单独运行：python -m services.memory_optimizer
    """
    global workflow, session_manager, db_engine, ai_service, feedback_service, smart_cache

    # 启动阶段
    try:
        # 1. 初始化异步数据库引擎并创建表（带重试，兼容 depends_on service_started）
        logger.info("正在初始化数据库...")
        await _retry_until_ready("数据库", lambda: create_tables(db_engine))
        logger.info("数据库表初始化完成")

        # 2. 初始化智能缓存服务 (新增步骤)
        logger.info("正在初始化智能缓存...")
        smart_cache = SmartCache()  # 从环境变量 REDIS_URL 读取配置
        logger.info("智能缓存初始化完成")

        # 3. 初始化 AI 服务，并注入缓存实例（关键修改）
        logger.info("正在初始化 AI 服务...")
        ai_service = SimpleAIService(cache=smart_cache)  # 传入缓存实例
        logger.info("AI 服务初始化完成")

        # 4. 初始化 SessionManager（异步 Redis 客户端），并对 Redis 做连接重试
        logger.info("正在初始化 SessionManager...")
        session_manager = SessionManager()

        async def _ping_redis():
            await session_manager.redis.ping()

        await _retry_until_ready("Redis", _ping_redis)
        logger.info("SessionManager 初始化完成")

        # 5. 初始化 FeedbackService（依赖 AsyncSessionLocal 与 Redis）
        logger.info("正在初始化 FeedbackService...")
        feedback_service = FeedbackService(AsyncSessionLocal, session_manager.redis)
        logger.info("FeedbackService 初始化完成")

        # 6. 初始化工作流图（注入 ai_service 以使用缓存并统计缓存命中）
        logger.info("正在初始化工作流...")
        workflow = create_workflow(ai_service)
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


class PrometheusMiddleware(BaseHTTPMiddleware):
    """记录请求次数与耗时的中间件；排除 /metrics 避免噪音。"""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)
        method = request.method
        path = request.url.path
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        REQUEST_LATENCY.labels(method=method, path=path).observe(duration)
        REQUEST_COUNT.labels(method=method, path=path).inc()
        return response


# 作为第一个（最外层）中间件添加，以最准确测量请求时间
app.add_middleware(PrometheusMiddleware)


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


async def get_feedback_service() -> AsyncGenerator[FeedbackService, None]:
    """
    异步依赖项：提供 FeedbackService 实例（内部通过 AsyncSessionLocal 获取有效数据库会话）。
    """
    if feedback_service is None:
        raise RuntimeError("FeedbackService 未初始化")
    yield feedback_service


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
    5. 将工作流结果更新到 Redis 会话中
    
    注意：session_id 由后端自动生成，不在请求体中接收。
    """
    try:
        user_id = request.user_id

        # 1. 根据 user_id 获取或创建用户档案（异步）
        profile = await get_or_create_user_profile(db, user_id)
        logger.info(f"获取/创建用户档案完成，user_id: {user_id}")

        # 2. 创建新会话，并将用户档案信息存入会话（异步）
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
        
        session_id = await sm.create_session(
            user_id=user_id,
            initial_data=session_data
        )
        logger.info(f"创建新会话完成，session_id: {session_id}")

        # 3. 执行工作流，将 session_id、user_id、tags（可选）和用户偏好传入初始状态
        initial_state = {
            "user_input": json.dumps({
                "user_id": user_id,
                "brand_name": request.brand_name,
                "product_desc": request.product_desc,
                "topic": request.topic,
                "tags": request.tags,
            }, ensure_ascii=False),
            "analysis": "",
            "content": "",
            "session_id": session_id,
            "user_id": user_id,
            "evaluation": {},
            "need_revision": False,
            "stage_durations": {},
            "analyze_cache_hit": False,
            "used_tags": [],
        }

        request_start = time.perf_counter()
        logger.info(f"开始执行工作流，session_id: {session_id}")
        result = await workflow.ainvoke(initial_state)
        request_duration_seconds = round(time.perf_counter() - request_start, 4)
        logger.info(f"工作流执行完成，完整结果Keys: {list(result.keys())}")
        logger.info(f"工作流执行完成，session_id: {session_id}")

        # 4. 将工作流结果更新到 Redis 会话中（含 tags 供后续 GET session 返回）
        used_tags_list = result.get("used_tags") if isinstance(result.get("used_tags"), list) else []
        existing_session_data = await sm.get_session(session_id)
        if existing_session_data and "initial_data" in existing_session_data:
            updated_initial_data = existing_session_data["initial_data"]
            updated_initial_data.update({
                "content": result["content"],
                "analysis": result["analysis"],
                "evaluation": result["evaluation"],
                "need_revision": result["need_revision"],
                "tags": used_tags_list,
                "used_tags": used_tags_list,
            })
            await sm.update_session(session_id, "initial_data", updated_initial_data)
            logger.info(f"会话数据已更新，session_id: {session_id}")

        # 5. 若有请求输入的 tags，记入用户档案供下次使用；并标记「用户显式写入」供 memory_optimizer 跳过覆盖
        if request.tags is not None and len(request.tags) > 0:
            profile.tags = request.tags
            try:
                await sm.redis.setex("user_tags_explicit:" + user_id, 7 * 24 * 3600, "1")
            except Exception as e:
                logger.warning("设置 user_tags_explicit 失败，optimizer 可能覆盖用户标签: %s", e)
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

        # 6. 返回成功响应（含所用 tags、请求耗时、阶段耗时、缓存命中说明）
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "session_id": session_id,
                    "user_id": user_id,
                    "content": result["content"],
                    "analysis": result["analysis"],
                    "evaluation": result.get("evaluation", {}),
                    "tags": used_tags_list,  # 本次实际传给模型的标签（请求覆盖或系统历史）
                    "used_tags": used_tags_list,
                    "timestamp": history.created_at.isoformat() if history.created_at else None,
                    "request_duration_seconds": request_duration_seconds,
                    "stage_durations": result.get("stage_durations", {}),
                    "analyze_cache_hit": result.get("analyze_cache_hit", False),
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


@app.post("/api/v1/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    fb: FeedbackService = Depends(get_feedback_service),
) -> JSONResponse:
    """
    提交反馈：根据 session_id 更新对应 InteractionHistory 的 user_rating、user_comment；
    若 rating >= 4 则触发画像优化入队。
    FeedbackService 内部通过 AsyncSessionLocal 获取有效数据库会话。
    """
    try:
        await fb.record(body.session_id, body.rating, body.comment)
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "session_id": body.session_id,
                    "rating": body.rating,
                    "comment": body.comment,
                },
            },
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error("提交反馈时出错: %s", e, exc_info=True)
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
            "create_content": "/api/v1/create (POST)",
            "feedback": "/api/v1/feedback (POST)"
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
            await session_manager.redis.ping()
            health_status["services"]["redis"] = "healthy"
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
    
    # 检查缓存服务（新增）
    health_status["services"]["smart_cache"] = "healthy" if smart_cache is not None else "unhealthy: not initialized"
    if smart_cache is None:
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
        
        # 从会话数据中提取变量
        initial_data = session_data.get("initial_data", {})
        user_id = session_data.get("user_id")
        content = initial_data.get("content", "")
        analysis = initial_data.get("analysis", "")
        evaluation = initial_data.get("evaluation", {})
        tags_list = initial_data.get("tags") if isinstance(initial_data.get("tags"), list) else []
        created_at = session_data.get("created_at", "")
        
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "session_id": session_id,
                    "user_id": user_id,
                    "content": content,
                    "analysis": analysis,
                    "evaluation": evaluation,
                    "tags": tags_list,
                    "used_tags": tags_list,
                    "timestamp": created_at,
                }
            },
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"获取会话信息时出错: {e}", exc_info=True)
        raise


@app.get("/metrics")
async def metrics():
    """Prometheus 指标端点"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    import asyncio
    from starlette.responses import Response
    
    # 在单独的线程中生成指标，避免阻塞事件循环
    data = await asyncio.to_thread(generate_latest)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
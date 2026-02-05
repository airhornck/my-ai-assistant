import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, List, Optional

# 加载 .env（必须在 database 等模块导入前执行，否则 DATABASE_URL 等会使用默认值）
from dotenv import load_dotenv
_root = Path(__file__).resolve().parent
for _f in (".env", ".env.dev", ".env.prod"):
    _p = _root / _f
    if _p.exists():
        load_dotenv(_p)
        break

from fastapi import Depends, File, Form, FastAPI, Query, Request, status, UploadFile
from pydantic import BaseModel
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from prometheus_client import Counter, Histogram
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine
from starlette.middleware.base import BaseHTTPMiddleware

from core.plugin_bus import DocumentQueryEvent, get_plugin_bus
from core.plugin_registry import get_registry
from database import (
    AsyncSessionLocal,
    InteractionHistory,
    UserProfile,
    engine,
    get_db,
    get_or_create_user_profile,
    create_tables,
    POOL_SIZE,
    MAX_OVERFLOW,
)
from memory.session_manager import SessionManager
from models.request import (
    ContentRequest,
    ChatResumeRequest,
    FeedbackRequest,
    FrontendChatRequest,
    NewChatRequest,
    RawAnalyzeRequest,
)
from services.ai_service import SimpleAIService
from core.intent import classify_feedback_after_creation
from core.intent.processor import SHORT_CASUAL_REPLIES
from services.input_service import (
    INTENT_COMMAND,
    INTENT_DOCUMENT_QUERY,
    InputProcessor,
)
from config.media_specs import needs_clarification, get_clarification_response
from datetime import datetime, timezone
from core.document import SessionDocumentBinding
from core.document.parser import SUPPORTED_DOC_EXTENSIONS
from core.link import extract_urls, fetch_link_context
from core.reference import extract_reference_supplement
from services.document_service import DocumentService
from services.feedback_service import FeedbackService
from cache.smart_cache import SmartCache
from domain.memory import MemoryService
from workflows.basic_workflow import create_workflow
from workflows.meta_workflow import build_meta_workflow

try:
    from langgraph.types import Command
except Exception:
    Command = None
from modules.knowledge_base.factory import get_knowledge_port
from modules.case_template.service import CaseTemplateService
from modules.methodology.service import MethodologyService


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
# analyze-deep 各阶段耗时（细粒度，便于定位瓶颈；仅 observe 不阻塞主流程）
ANALYZE_DEEP_PHASE_DURATION = Histogram(
    "analyze_deep_phase_duration_seconds",
    "analyze-deep 各阶段耗时（规划/子步骤/编译）",
    ["phase"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)
# meta_workflow 三阶段细粒度性能监控（单位：秒，符合 Prometheus 规范）
METRIC_PLANNING_DURATION = Histogram(
    "meta_workflow_planning_duration_seconds",
    "规划节点耗时",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)
METRIC_ORCHESTRATION_DURATION = Histogram(
    "meta_workflow_orchestration_duration_seconds",
    "编排节点耗时",
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)
METRIC_COMPILATION_DURATION = Histogram(
    "meta_workflow_compilation_duration_seconds",
    "编译节点耗时",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
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


async def track_duration(metric, func, *args, **kwargs):
    """
    异步监控装饰器：记录 func 执行耗时（秒）并 observe 到 metric，非侵入式。
    使用 try...finally 保证即使节点执行出错，耗时也会被记录。
    """
    start = time.time()
    try:
        result = await func(*args, **kwargs)
        return result
    finally:
        duration = time.time() - start
        if metric is not None:
            try:
                metric.observe(duration)
            except Exception as e:
                logger.warning("track_duration 记录指标失败: %s", e)


async def _update_session_intent(
    sm: SessionManager,
    session_id: str,
    brand_name: str,
    product_desc: str,
    topic: str,
    intent: str = "",
    raw_query: str = "",
) -> None:
    """将会话意图状态写入 session.initial_data.session_intent，供后续轮次延续上下文。"""
    if not (brand_name or product_desc or topic):
        return
    try:
        data = await sm.get_session(session_id)
        if not data or not isinstance(data.get("initial_data"), dict):
            return
        initial = dict(data["initial_data"])
        initial["session_intent"] = {
            "brand_name": brand_name,
            "product_desc": product_desc,
            "topic": topic,
            "intent": intent,
            "raw_query": raw_query,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await sm.update_session(session_id, "initial_data", initial)
    except Exception as e:
        logger.debug("更新 session_intent 失败（不影响主流程）: %s", e)


async def _derive_and_update_tags_background(
    user_id: str,
    topic: str,
    brand_name: str,
    product_desc: str,
    raw_query: str,
    content_preview: str,
    ai_svc: SimpleAIService,
    sm: SessionManager,
) -> None:
    """
    P0/P1: 深度成功后异步提炼标签并回写 UserProfile。
    若 user_tags_explicit 存在则跳过，不覆盖用户显式标签。
    """
    try:
        if sm and hasattr(sm, "redis"):
            if await sm.redis.get("user_tags_explicit:" + user_id):
                return
        summary = f"topic={topic}; brand={brand_name}; product={product_desc}; query={raw_query}; output={content_preview[:300]}"
        if not summary.strip():
            return
        from langchain_core.messages import HumanMessage, SystemMessage
        system = "根据用户本次营销交互摘要，提炼 2-4 个兴趣标签（如「科技数码」「偏爱简洁文案」「关注促销」）。只输出 JSON 数组，不要其他文字。"
        user = f"【交互摘要】\n{summary}\n\n只输出 JSON 数组。"
        try:
            client = await ai_svc.router.route("planning", "low")
            resp = await client.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
            raw = (resp.content if hasattr(resp, "content") else str(resp) or "").strip()
            for p in ("```json", "```"):
                if raw.startswith(p):
                    raw = raw[len(p):].strip()
            if raw.endswith("```"):
                raw = raw[:raw.rfind("```")].strip()
            arr = json.loads(raw) if raw else []
            new_tags = [str(x).strip() for x in (arr if isinstance(arr, list) else []) if x][:4]
        except Exception as e:
            logger.debug("标签提炼 LLM 失败: %s", e)
            return
        if not new_tags:
            return
        async with AsyncSessionLocal() as session:
            r = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
            profile = r.scalar_one_or_none()
            if not profile:
                return
            existing = list(profile.tags) if isinstance(getattr(profile, "tags", None), list) else []
            merged = list(dict.fromkeys(existing + new_tags))[:6]
            await session.execute(update(UserProfile).where(UserProfile.user_id == user_id).values(tags=merged))
            await session.commit()
        logger.info("user_id=%s 已更新 tags=%s", user_id, merged)
    except Exception as e:
        logger.warning("_derive_and_update_tags_background 失败: %s", e)


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
        logger.info("数据库表初始化完成（连接池 pool_size=%s, max_overflow=%s）", POOL_SIZE, MAX_OVERFLOW)

        # 2. 初始化智能缓存服务 (新增步骤)
        logger.info("正在初始化智能缓存...")
        smart_cache = SmartCache()  # 从环境变量 REDIS_URL 读取配置
        logger.info("智能缓存初始化完成")

        # 3. 初始化 AI 服务，并注入缓存与活动策划插件依赖（方法论/案例/知识库）
        logger.info("正在初始化 AI 服务...")
        ai_service = SimpleAIService(
            cache=smart_cache,
            methodology_service=MethodologyService(),
            case_service=CaseTemplateService(AsyncSessionLocal),
            knowledge_port=get_knowledge_port(smart_cache) if smart_cache else None,
        )
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

        # 6. 初始化插件注册中心并加载工作流（插件加载失败仅记录，不影响主流程）
        logger.info("正在初始化插件注册中心...")
        memory_svc_for_plugins = MemoryService(cache=smart_cache)
        registry = get_registry()
        registry.register_workflow("content", lambda cfg: create_workflow(cfg.get("ai_service")))
        registry.init_plugins({
            "ai_service": ai_service,
            "memory_service": memory_svc_for_plugins,
            "cache": smart_cache,
        })
        # 主流程使用 content 工作流；若未加载成功则降级为直接构建
        workflow = registry.get_workflow("content")
        if workflow is None:
            logger.warning("插件 content 未加载，主流程降级为直接构建工作流")
            workflow = create_workflow(ai_service)
        logger.info("工作流初始化完成")

        # 定时插件首次刷新：在 lifespan 完全就绪后执行，确保 env/config 已加载
        if hasattr(ai_service, "_analysis_plugin_center") and ai_service._analysis_plugin_center:
            ai_service._analysis_plugin_center.run_initial_refresh()

        logger.info("✅ 应用启动完成，所有服务已就绪")
    except Exception as e:
        logger.error(f"❌ 应用启动失败: {e}", exc_info=True)
        raise

    yield

    # 关闭阶段：清理资源
    logger.info("正在关闭应用...")
    try:
        if ai_service is not None and hasattr(ai_service, "_analysis_plugin_center"):
            center = getattr(ai_service, "_analysis_plugin_center", None)
            if center is not None:
                center.stop_scheduled_tasks()
    except Exception:
        pass

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

# 数据闭环、案例模板、营销方法论 API（独立模块）
from routers.data_and_knowledge import router as data_knowledge_router
app.include_router(data_knowledge_router, prefix="/api/v1")


# 活动策划已收口到统一入口：frontend/chat 走 meta_workflow，task_type=campaign_or_copy 时编排层内部走 strategy_orchestrator（方案 A）


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


async def get_document_service(db: AsyncSession = Depends(get_db)) -> AsyncGenerator[DocumentService, None]:
    """异步依赖项：提供 DocumentService 实例（兼容旧接口）。"""
    yield DocumentService(db)


async def get_session_document_binding(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[SessionDocumentBinding, None]:
    """异步依赖项：提供 SessionDocumentBinding 实例（会话级文档绑定）。"""
    yield SessionDocumentBinding(db)


async def get_memory_service() -> AsyncGenerator[MemoryService, None]:
    """异步依赖项：提供 MemoryService 实例（用户记忆、画像、标签）。"""
    yield MemoryService(cache=smart_cache if smart_cache else None)


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


@app.post("/api/v1/create", tags=["内容"])
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
        
        create_result = await sm.create_session(
            user_id=user_id,
            initial_data=session_data,
        )
        session_id = create_result["session_id"]
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
        # 确保 tags/used_tags 一定从 result 取出并包含在响应中，避免旧版本或缓存导致缺失
        tags_in_response = result.get("used_tags") if isinstance(result.get("used_tags"), list) else []
        response_data = {
            "session_id": session_id,
            "user_id": user_id,
            "tags": tags_in_response,
            "used_tags": tags_in_response,
            "content": result["content"],
            "analysis": result["analysis"],
            "evaluation": result.get("evaluation", {}),
            "timestamp": history.created_at.isoformat() if history.created_at else None,
            "request_duration_seconds": request_duration_seconds,
            "stage_durations": result.get("stage_durations", {}),
            "analyze_cache_hit": result.get("analyze_cache_hit", False),
        }
        return JSONResponse(
            content={"success": True, "data": response_data},
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


# 深度分析端点超时（秒）：元工作流含多步规划与子工作流，耗时长
ANALYZE_DEEP_TIMEOUT_SECONDS = 300


@app.post(
    "/api/v1/analyze-deep",
    summary="深度分析（元工作流）",
    description="使用元工作流进行规划→编排子工作流→汇总报告，返回最终内容与完整思考过程（thinking_process）。",
    tags=["内容"],
)
async def analyze_deep(
    request: ContentRequest,
    db: AsyncSession = Depends(get_db),
    sm: SessionManager = Depends(get_session_manager),
    ai: SimpleAIService = Depends(get_ai_service),
) -> JSONResponse:
    """
    深度分析接口：使用元工作流（规划 → 编排子工作流 → 汇总报告）。
    响应包含最终内容、完整思考过程（thinking_process，每步含 step / thought / timestamp）。
    此端点执行时间较长，请设置足够超时（服务端默认 """ + str(ANALYZE_DEEP_TIMEOUT_SECONDS) + """s）。
    """
    try:
        user_id = request.user_id

        profile = await get_or_create_user_profile(db, user_id)
        logger.info("analyze-deep: 获取/创建用户档案完成, user_id=%s", user_id)

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
            },
        }
        create_result = await sm.create_session(user_id=user_id, initial_data=session_data)
        session_id = create_result["session_id"]
        logger.info("analyze-deep: 创建会话完成, session_id=%s", session_id)

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
            "plan": [],
            "task_type": "",
            "current_step": 0,
            "thinking_logs": [],
            "step_outputs": [],
            "search_context": "",
            "memory_context": "",
            "kb_context": "",
            "effective_tags": [],
            "analysis_plugins": [],
            "generation_plugins": [],
        }

        meta = build_meta_workflow(
            ai_service=ai,
            knowledge_port=get_knowledge_port(smart_cache) if smart_cache else None,
            metrics={
                "planning": METRIC_PLANNING_DURATION,
                "orchestration": METRIC_ORCHESTRATION_DURATION,
                "compilation": METRIC_COMPILATION_DURATION,
            },
            track_duration=track_duration,
        )
        config = {"configurable": {"thread_id": session_id}}
        try:
            result = await asyncio.wait_for(
                meta.ainvoke(initial_state, config=config),
                timeout=ANALYZE_DEEP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("analyze-deep 超时, session_id=%s", session_id)
            return JSONResponse(
                content={
                    "success": False,
                    "error": "深度分析执行超时，请稍后重试或减少步骤。",
                    "session_id": session_id,
                },
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        if result.get("__interrupt__"):
            return JSONResponse(
                content={
                    "success": True,
                    "status": "interrupt",
                    "message": "评估完成，是否修订？请调用 POST /api/v1/chat/resume 传入 human_decision（revise | skip）。",
                    "session_id": session_id,
                    "__interrupt__": result.get("__interrupt__"),
                    "state_snapshot": {k: v for k, v in result.items() if k != "__interrupt__" and not k.startswith("_")},
                },
                status_code=status.HTTP_200_OK,
            )
        # 细粒度阶段耗时（仅 observe，不影响主流程）
        for phase_key, phase_label in (
            ("planning_duration_sec", "planning"),
            ("orchestration_duration_sec", "orchestration"),
            ("compilation_duration_sec", "compilation"),
        ):
            val = result.get(phase_key)
            if val is not None and isinstance(val, (int, float)) and val >= 0:
                ANALYZE_DEEP_PHASE_DURATION.labels(phase=phase_label).observe(float(val))

        thinking_logs = result.get("thinking_logs")
        if not isinstance(thinking_logs, list):
            thinking_logs = []

        final_content = result.get("content") or ""

        existing_session_data = await sm.get_session(session_id)
        if existing_session_data and "initial_data" in existing_session_data:
            updated_initial_data = existing_session_data["initial_data"]
            updated_initial_data.update({
                "content": final_content,
                "analysis": result.get("analysis", ""),
                "evaluation": result.get("evaluation", {}),
                "thinking_logs": thinking_logs,
            })
            await sm.update_session(session_id, "initial_data", updated_initial_data)

        history = InteractionHistory(
            user_id=user_id,
            session_id=session_id,
            user_input=json.dumps({
                "brand_name": request.brand_name,
                "product_desc": request.product_desc,
                "topic": request.topic,
            }, ensure_ascii=False),
            ai_output=final_content,
        )
        db.add(history)
        await db.commit()
        logger.info("analyze-deep: 交互历史已保存, session_id=%s", session_id)

        content_sections = result.get("content_sections") or {}
        return JSONResponse(
            content={
                "success": True,
                "data": final_content,
                "thinking_process": thinking_logs,
                "content_sections": content_sections,
                "session_id": session_id,
            },
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        logger.error("analyze-deep 出错: %s", e, exc_info=True)
        raise


def _err_response(
    message: str,
    stage: str,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    **extra: Any,
) -> JSONResponse:
    """统一错误响应：便于前端根据 stage 与 error 做提示。"""
    body = {"success": False, "error": message, "stage": stage, **extra}
    return JSONResponse(content=body, status_code=status_code)


@app.post(
    "/api/v1/analyze-deep/raw",
    summary="深度分析（原始输入）",
    description="用户输入 → InputProcessor 意图识别 → 若涉及文档则发布 DocumentQueryEvent 由插件补全 → 增强 ProcessedInput 送入 MetaWorkflow。各环节失败均有 stage 与 error 返回。",
    tags=["内容"],
)
async def analyze_deep_raw(
    request: RawAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    sm: SessionManager = Depends(get_session_manager),
    ai: SimpleAIService = Depends(get_ai_service),
    doc_binding: SessionDocumentBinding = Depends(get_session_document_binding),
) -> JSONResponse:
    """
    自由输入主流程：InputProcessor 识别意图 → 若 document_query 则插件总线调度文档插件增强 ProcessedInput → MetaWorkflow 深度思考与执行。
    每步失败均返回清晰 stage 与 error，便于前端展示。
    """
    user_id = request.user_id
    session_id: str = ""

    # 1. 获取/创建用户档案
    try:
        profile = await get_or_create_user_profile(db, user_id)
        logger.info("analyze-deep-raw: 获取/创建用户档案完成, user_id=%s", user_id)
    except Exception as e:
        logger.exception("analyze-deep-raw 阶段 profile 失败")
        return _err_response(
            "获取或创建用户档案失败，请稍后重试。",
            stage="profile",
            detail=str(e),
        )

    # 2. 解析或创建会话
    try:
        if request.session_id and request.session_id.strip():
            existing = await sm.get_session(request.session_id.strip())
            if existing:
                session_id = request.session_id.strip()
                logger.info("analyze-deep-raw: 沿用已有会话, session_id=%s", session_id)
            else:
                _si = {"brand_name": (profile.brand_name or "").strip(), "product_desc": "", "topic": (profile.industry or "").strip(), "intent": "", "raw_query": "", "updated_at": datetime.now(timezone.utc).isoformat()} if (profile.brand_name or profile.industry) else {}
                session_data = {
                    "user_profile": {"user_id": profile.user_id, "brand_name": profile.brand_name, "industry": profile.industry, "preferred_style": profile.preferred_style},
                    "request_info": {},
                    "session_intent": _si,
                }
                create_result = await sm.create_session(user_id=user_id, initial_data=session_data)
                session_id = create_result["session_id"]
                logger.info("analyze-deep-raw: 指定会话不存在，创建新会话, session_id=%s", session_id)
        else:
            _si = {"brand_name": (profile.brand_name or "").strip(), "product_desc": "", "topic": (profile.industry or "").strip(), "intent": "", "raw_query": "", "updated_at": datetime.now(timezone.utc).isoformat()} if (profile.brand_name or profile.industry) else {}
            session_data = {
                "user_profile": {"user_id": profile.user_id, "brand_name": profile.brand_name, "industry": profile.industry, "preferred_style": profile.preferred_style},
                "request_info": {},
                "session_intent": _si,
            }
            create_result = await sm.create_session(user_id=user_id, initial_data=session_data)
            session_id = create_result["session_id"]
            logger.info("analyze-deep-raw: 创建会话完成, session_id=%s", session_id)
    except Exception as e:
        logger.exception("analyze-deep-raw 阶段 session 失败")
        return _err_response(
            "创建或恢复会话失败，请稍后重试。",
            stage="session",
            detail=str(e),
        )

    # 2.5 加载会话文档 + 抓取链接内容
    session_doc_context = ""
    try:
        session_doc_context = await doc_binding.get_session_document_context(session_id)
    except Exception as e:
        logger.warning("analyze-deep-raw: 加载会话文档失败: %s", e)
    link_context = ""
    try:
        urls = extract_urls(request.raw_input)
        if urls:
            link_context = await fetch_link_context(urls)
            if link_context:
                logger.info("analyze-deep-raw: 已抓取 %d 个链接内容", len(urls))
    except Exception as e:
        logger.warning("analyze-deep-raw: 链接抓取失败: %s", e)
    combined_doc_context = (session_doc_context or "")
    if link_context:
        combined_doc_context = (combined_doc_context + "\n\n【链接引用内容】\n" + link_context).strip()

    # 2.9 加载会话意图状态（用于文档/链接轮次延续主推广对象）
    _existing = await sm.get_session(session_id)
    _session_intent = {}
    if _existing and isinstance(_existing.get("initial_data"), dict):
        _session_intent = (_existing["initial_data"].get("session_intent") or {}) or {}

    # 3. 意图识别与输入标准化
    try:
        input_processor = InputProcessor(ai_service=ai)
        processed = await input_processor.process(
            raw_input=request.raw_input,
            session_id=session_id,
            user_id=user_id,
            session_document_context=combined_doc_context or None,
        )
    except Exception as e:
        logger.exception("analyze-deep-raw 阶段 intent 失败")
        return _err_response(
            "意图识别失败，请简化输入后重试。",
            stage="intent_recognition",
            session_id=session_id,
            detail=str(e),
        )

    intent = processed.get("intent", "")
    if intent == INTENT_COMMAND:
        return JSONResponse(
            content={
                "success": True,
                "intent": intent,
                "command": processed.get("command"),
                "session_id": session_id,
                "message": "命令已识别，由客户端处理",
            },
            status_code=status.HTTP_200_OK,
        )

    if intent == INTENT_CASUAL_CHAT:
        reply = await ai.reply_casual(
            message=request.raw_input,
            history_text="",
        )
        return JSONResponse(
            content={
                "success": True,
                "intent": intent,
                "session_id": session_id,
                "data": reply,
                "thinking_process": [],
            },
            status_code=status.HTTP_200_OK,
        )

    # 4. 若涉及文档查询，通过插件总线调度文档插件，生成增强 ProcessedInput
    if intent == INTENT_DOCUMENT_QUERY:
        payload = {
            "processed_input": processed,
            "user_id": user_id,
            "session_id": session_id,
            "enhanced": None,
        }
        try:
            bus = get_plugin_bus()
            # model_construct 保留 data 引用，插件对 event.data 的写回会反映到 payload
            event = DocumentQueryEvent.model_construct(source="main", data=payload)
            await bus.publish(event)
            enhanced = payload.get("enhanced")
            if enhanced and isinstance(enhanced, dict):
                for k, v in enhanced.items():
                    processed[k] = v
                logger.info("analyze-deep-raw: 已合并文档插件增强结果")
        except Exception as e:
            logger.warning("analyze-deep-raw: 文档插件总线处理异常，继续使用原始 ProcessedInput: %s", e, exc_info=True)
            # 不阻断流程，仅记录；仍用当前 processed 进入元工作流

    # 5. 合并会话意图并做澄清检查
    structured = processed.get("structured_data") or {}
    brand_name = (structured.get("brand_name") or "").strip() or (_session_intent.get("brand_name") or "").strip()
    product_desc = (structured.get("product_desc") or "").strip() or (_session_intent.get("product_desc") or "").strip()
    topic = (structured.get("topic") or "").strip() or (_session_intent.get("topic") or "").strip() or (processed.get("raw_query") or "")
    raw_query = (processed.get("raw_query") or "").strip()

    if needs_clarification(
        raw_query=raw_query,
        topic=topic,
        product_desc=product_desc,
        brand_name=brand_name,
        intent=intent,
    ):
        summary = product_desc or brand_name or raw_query or request.raw_input
        clarification = get_clarification_response(
            product_summary=summary,
            brand_name=brand_name,
            product_desc=product_desc,
            topic=topic,
        )
        await _update_session_intent(sm, session_id, brand_name, product_desc, topic, intent, raw_query)
        return JSONResponse(
            content={
                "success": True,
                "intent": "clarification",
                "session_id": session_id,
                "data": clarification,
                "thinking_process": [],
            },
            status_code=status.HTTP_200_OK,
        )

    # 5.5 参考材料单独解析：提取对主推广对象的补充
    reference_supplement = ""
    if combined_doc_context and combined_doc_context.strip():
        main_topic_desc = f"{brand_name or ''} {product_desc or ''}，{topic or ''}".strip() or raw_query[:200]
        if main_topic_desc:
            try:
                reference_supplement = await extract_reference_supplement(
                    main_topic=main_topic_desc,
                    reference_raw=combined_doc_context,
                    llm_client=ai._llm,
                )
                if reference_supplement:
                    logger.info("analyze-deep-raw: 已提取参考材料补充, 长度=%d", len(reference_supplement))
            except Exception as e:
                logger.warning("analyze-deep-raw: 参考材料补充提取失败: %s", e)

    # 6. 用（可能已增强的）ProcessedInput 构建 initial_state
    user_input_payload = {
        "user_id": user_id,
        "brand_name": brand_name,
        "product_desc": product_desc,
        "topic": topic,
        "tags": request.tags,
        "raw_query": processed.get("raw_query"),
        "intent": intent,
        "explicit_content_request": processed.get("explicit_content_request", False),
        "analysis_plugin_result": processed.get("analysis_plugin_result"),
        "session_document_context": reference_supplement if reference_supplement else None,
    }
    initial_state = {
        "user_input": json.dumps(user_input_payload, ensure_ascii=False),
        "analysis": "",
        "content": "",
        "session_id": session_id,
        "user_id": user_id,
        "evaluation": {},
        "need_revision": False,
        "stage_durations": {},
        "analyze_cache_hit": False,
        "used_tags": [],
        "plan": [],
        "task_type": "",
        "current_step": 0,
        "thinking_logs": [],
        "step_outputs": [],
        "search_context": "",
        "memory_context": "",
        "kb_context": "",
        "effective_tags": [],
        "analysis_plugins": [],
        "generation_plugins": [],
    }

    # 7. 执行元工作流（多轮：thread_id 与 session_id 一致，支持断点续跑与人工介入恢复）
    config = {"configurable": {"thread_id": session_id}}
    try:
        meta = build_meta_workflow(
            ai_service=ai,
            knowledge_port=get_knowledge_port(smart_cache) if smart_cache else None,
            metrics={
                "planning": METRIC_PLANNING_DURATION,
                "orchestration": METRIC_ORCHESTRATION_DURATION,
                "compilation": METRIC_COMPILATION_DURATION,
            },
            track_duration=track_duration,
        )
        result = await asyncio.wait_for(
            meta.ainvoke(initial_state, config=config),
            timeout=ANALYZE_DEEP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("analyze-deep-raw 超时, session_id=%s", session_id)
        return _err_response(
            "深度分析执行超时，请稍后重试或减少步骤。",
            stage="meta_workflow",
            session_id=session_id,
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except Exception as e:
        logger.exception("analyze-deep-raw 阶段 meta_workflow 失败")
        try:
            await db.rollback()
        except Exception:
            pass
        return _err_response(
            "元工作流执行失败，请稍后重试。",
            stage="meta_workflow",
            session_id=session_id,
            detail=str(e),
        )

    if result.get("__interrupt__"):
        return JSONResponse(
            content={
                "success": True,
                "status": "interrupt",
                "message": "评估完成，是否修订？请调用 POST /api/v1/chat/resume 传入 session_id 与 human_decision（revise | skip）。",
                "session_id": session_id,
                "__interrupt__": result.get("__interrupt__"),
                "state_snapshot": {k: v for k, v in result.items() if k != "__interrupt__" and not k.startswith("_")},
            },
            status_code=status.HTTP_200_OK,
        )

    # 7. 记录阶段耗时与更新会话
    for phase_key, phase_label in (
        ("planning_duration_sec", "planning"),
        ("orchestration_duration_sec", "orchestration"),
        ("compilation_duration_sec", "compilation"),
    ):
        val = result.get(phase_key)
        if val is not None and isinstance(val, (int, float)) and val >= 0:
            ANALYZE_DEEP_PHASE_DURATION.labels(phase=phase_label).observe(float(val))

    thinking_logs = result.get("thinking_logs") or []
    final_content = result.get("content") or ""
    try:
        existing_session_data = await sm.get_session(session_id)
        if existing_session_data and "initial_data" in existing_session_data:
            updated_initial_data = dict(existing_session_data["initial_data"])
            updated_initial_data.update({
                "content": final_content,
                "analysis": result.get("analysis", ""),
                "evaluation": result.get("evaluation", {}),
                "thinking_logs": thinking_logs,
                "session_intent": {
                    "brand_name": brand_name,
                    "product_desc": product_desc,
                    "topic": topic,
                    "intent": intent,
                    "raw_query": raw_query,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            })
            await sm.update_session(session_id, "initial_data", updated_initial_data)
    except Exception as e:
        logger.warning("analyze-deep-raw: 更新会话数据失败（不影响返回）: %s", e)

    # 8. 保存交互历史
    try:
        history = InteractionHistory(
            user_id=user_id,
            session_id=session_id,
            user_input=json.dumps(
                {"brand_name": brand_name, "product_desc": product_desc, "topic": topic, "raw_query": processed.get("raw_query")},
                ensure_ascii=False,
            ),
            ai_output=final_content,
        )
        db.add(history)
        await db.commit()
        logger.info("analyze-deep-raw: 交互历史已保存, session_id=%s", session_id)
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        logger.exception("analyze-deep-raw 阶段 save_history 失败")
        return _err_response(
            "保存交互历史失败，结果已生成但未持久化。",
            stage="save_history",
            session_id=session_id,
            detail=str(e),
        )

    # P0/P1: 深度成功后异步提炼标签并回写 profile
    req_tags = getattr(request, "tags", None) or []
    if not (req_tags and len(req_tags) > 0):
        asyncio.create_task(_derive_and_update_tags_background(
            user_id=user_id,
            topic=topic,
            brand_name=brand_name,
            product_desc=product_desc,
            raw_query=raw_query,
            content_preview=(final_content or "")[:400],
            ai_svc=ai,
            sm=sm,
        ))

    content_sections = result.get("content_sections") or {}
    return JSONResponse(
        content={
            "success": True,
            "data": final_content,
            "thinking_process": thinking_logs,
            "content_sections": content_sections,
            "session_id": session_id,
            "intent": intent,
        },
        status_code=status.HTTP_200_OK,
    )


@app.post(
    "/api/v1/chat/new",
    summary="新建对话",
    description="新建对话：保持 user_id 不变，仅创建新的 session_id 与 thread_id。session_id 为对话 ID，thread_id 供 LangGraph 断点续跑使用。",
    tags=["会话"],
)
async def chat_new(
    request: NewChatRequest,
    sm: SessionManager = Depends(get_session_manager),
) -> JSONResponse:
    """
    新建对话链：不传 parent_thread_id，创建新 thread_id 和新 session_id，
    返回二者供客户端后续请求使用。
    """
    try:
        create_result = await sm.create_session(
            user_id=request.user_id,
            initial_data={},
            parent_thread_id=None,
        )
        session_id = create_result["session_id"]
        thread_id = create_result["thread_id"]
        logger.info("chat/new: 新建对话链, thread_id=%s, session_id=%s", thread_id, session_id)
        return JSONResponse(
            content={
                "success": True,
                "thread_id": thread_id,
                "session_id": session_id,
            },
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error("chat/new 出错: %s", e, exc_info=True)
        raise


@app.get(
    "/api/v1/frontend/session/init",
    summary="前端会话初始化",
    description="为前端提供初始化入口：生成默认 user_id（基于时间戳+随机数，演示用），创建初始会话并返回 user_id 与 session_id。生产环境需结合认证系统。",
    tags=["前端"],
)
async def frontend_session_init(
    request: Request,
    sm: SessionManager = Depends(get_session_manager),
) -> JSONResponse:
    """
    前端会话初始化：
    1. 生成默认 user_id（演示用：时间戳+随机数；生产需认证）
    2. 调用 SessionManager 创建初始会话
    3. 返回 user_id 和 session_id
    """
    try:
        # 生成默认 user_id（演示用）
        # 生产环境：从 JWT token 或认证系统获取真实 user_id
        import uuid
        user_id = f"frontend_user_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        
        # 创建初始会话
        create_result = await sm.create_session(
            user_id=user_id,
            initial_data={"request_info": {}},
            parent_thread_id=None,
        )
        session_id = create_result["session_id"]
        thread_id = create_result["thread_id"]
        
        logger.info(
            "frontend/session/init: 初始化成功, user_id=%s, session_id=%s, thread_id=%s",
            user_id, session_id, thread_id
        )
        
        return JSONResponse(
            content={
                "success": True,
                "user_id": user_id,
                "session_id": session_id,
                "thread_id": thread_id,
            },
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error("frontend/session/init 出错: %s", e, exc_info=True)
        return JSONResponse(
            content={
                "success": False,
                "error": "初始化会话失败，请稍后重试。",
                "detail": str(e),
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@app.post(
    "/api/v1/frontend/chat",
    summary="前端聊天统一接口",
    description="统一入口，根据意图自动路由：【闲聊】走快捷回复；【创作】走策略脑+分析脑+生成脑。每轮重新识别意图，支持会话中从闲聊切换到创作。",
    tags=["前端"],
)
async def frontend_chat(
    request: FrontendChatRequest,
    stream: bool = Query(False, description="是否流式返回每步 state（SSE）"),
    db: AsyncSession = Depends(get_db),
    sm: SessionManager = Depends(get_session_manager),
    ai: SimpleAIService = Depends(get_ai_service),
    doc_binding: SessionDocumentBinding = Depends(get_session_document_binding),
    memory_svc: MemoryService = Depends(get_memory_service),
) -> JSONResponse:
    """
    前端聊天统一接口：意图驱动自动路由。
    - 闲聊（casual_chat）：快捷回复，多轮对话，保存到 InteractionHistory
    - 创作（free_discussion 等）：策略脑规划 → 编排执行 → 输出
    会话过期返回 440 供前端重新初始化。
    """
    user_id = request.user_id
    message = request.message.strip()
    session_id = request.session_id
    
    if not message:
        return JSONResponse(
            content={
                "success": False,
                "error": "消息内容为空",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    
    
    # 1. 处理会话：检查 session_id，若无效则创建新会话
    try:
        if session_id and session_id.strip():
            existing = await sm.get_session(session_id.strip())
            if existing:
                session_id = session_id.strip()
                logger.info("frontend/chat: 使用已有会话, session_id=%s", session_id)
            else:
                # 会话过期，返回特定错误码 440
                logger.warning("frontend/chat: 会话过期, session_id=%s", session_id)
                return JSONResponse(
                    content={
                        "success": False,
                        "error": "会话已过期，请重新初始化",
                        "error_code": "SESSION_EXPIRED",
                    },
                    status_code=440,  # 440 Login Time-out（非标准，用于前端识别会话过期）
                )
        else:
            # 创建新会话（P0: 从 UserProfile 预填 session_intent）
            profile = await get_or_create_user_profile(db, user_id)
            session_intent_prefill = {}
            if profile.brand_name or profile.industry:
                session_intent_prefill = {
                    "brand_name": (profile.brand_name or "").strip(),
                    "product_desc": "",
                    "topic": (profile.industry or "").strip(),
                    "intent": "",
                    "raw_query": "",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            session_data = {
                "user_profile": {
                    "user_id": profile.user_id,
                    "brand_name": profile.brand_name,
                    "industry": profile.industry,
                    "preferred_style": profile.preferred_style,
                },
                "request_info": {},
                "session_intent": session_intent_prefill if session_intent_prefill else {},
            }
            create_result = await sm.create_session(user_id=user_id, initial_data=session_data)
            session_id = create_result["session_id"]
            logger.info("frontend/chat: 创建新会话, session_id=%s", session_id)
    except Exception as e:
        logger.exception("frontend/chat: 会话处理失败")
        return JSONResponse(
            content={
                "success": False,
                "error": "会话处理失败，请稍后重试。",
                "detail": str(e),
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    
    # 2. 加载会话附加文档上下文（用于理解对话时引用）
    session_doc_context = ""
    try:
        session_doc_context = await doc_binding.get_session_document_context(session_id)
        if session_doc_context:
            logger.info("frontend/chat: 已加载会话文档上下文, session_id=%s, 长度=%d", session_id, len(session_doc_context))
        else:
            logger.debug("frontend/chat: 会话无附加文档, session_id=%s", session_id)
    except Exception as e:
        logger.warning("frontend/chat: 加载会话文档上下文失败（不影响主流程）: %s", e)

    # 2.5 提取消息中的链接并抓取内容
    link_context = ""
    try:
        urls = extract_urls(message)
        if urls:
            link_context = await fetch_link_context(urls)
            if link_context:
                logger.info("frontend/chat: 已抓取 %d 个链接内容", len(urls))
    except Exception as e:
        logger.warning("frontend/chat: 链接抓取失败（不影响主流程）: %s", e)

    combined_doc_context = (session_doc_context or "")
    if link_context:
        combined_doc_context = (combined_doc_context + "\n\n【链接引用内容】\n" + link_context).strip()

    # 2.9 加载会话意图状态（用于文档/链接轮次延续主推广对象）
    existing_session_data = await sm.get_session(session_id)
    session_intent = {}
    if existing_session_data and isinstance(existing_session_data.get("initial_data"), dict):
        session_intent = (existing_session_data["initial_data"].get("session_intent") or {}) or {}

    # 3. 解析对话历史（用于上下文记忆）
    history = getattr(request, "history", None) or []
    history_parts = []
    if history and isinstance(history, list):
        for h in history[-10:]:  # 最多 10 条
            if isinstance(h, dict):
                role = h.get("role", "user")
                content = (h.get("content") or "").strip()
                if content:
                    history_parts.append(f"{'用户' if role == 'user' else '助手'}：{content[:300]}")
    history_text = ("以下是近期对话：\n" + "\n".join(history_parts) + "\n\n") if history_parts else ""
    conversation_context = "\n".join(history_parts) if history_parts else ""

    # 2.10 通过意图识别判断：是否采纳后续建议 / 是否为模糊评价（需生成澄清性问题）
    suggested_next_plan_from_session = None
    previous_was_creation = False
    if existing_session_data and isinstance(existing_session_data.get("initial_data"), dict):
        init = existing_session_data["initial_data"]
        suggested_next_plan_from_session = init.get("suggested_next_plan")
        # 上轮是否为创作输出（含 generate/evaluate）；若仅为闲聊则 False。「还好吧」在闲聊延续时表示「我还好」，创作结果后表示对内容的模糊评价
        previous_was_creation = bool(init.get("last_turn_was_creation"))
    has_suggested = bool(
        suggested_next_plan_from_session
        and isinstance(suggested_next_plan_from_session, list)
        and len(suggested_next_plan_from_session) > 0
    )
    last_role = None
    if history and isinstance(history, list) and len(history) >= 1:
        last_item = history[-1]
        if isinstance(last_item, dict):
            last_role = last_item.get("role", "user")
    msg_clean = message.strip().strip("。！？,，、 ")
    feedback_result = classify_feedback_after_creation(msg_clean, has_suggested, last_role, previous_was_creation)
    accepted_suggestion_this_request = feedback_result.accepted_suggestion
    has_ambiguous_feedback_after_creation = feedback_result.ambiguous_feedback
    if accepted_suggestion_this_request and not suggested_next_plan_from_session and last_role == "assistant":
        suggested_next_plan_from_session = [{"step": "generate", "params": {}, "reason": "用户采纳后续建议"}]
        logger.info("frontend/chat: 用户采纳后续建议(兜底), message=%s", message.strip())
    elif accepted_suggestion_this_request:
        logger.info("frontend/chat: 用户采纳后续建议, message=%s, reason=%s", message.strip(), feedback_result.reason)
    elif has_ambiguous_feedback_after_creation:
        logger.info("frontend/chat: 用户模糊评价(将生成澄清性问题), message=%s", message.strip())

    # 2.11 判断是否为「对上文内容的风格/平台改写」（如「我想生成B站风格的」→ 改写上一轮内容为 B站 风格，而非重新做活动方案）
    rewrite_previous_for_platform = False
    session_previous_content = None
    rewrite_platform = ""
    if existing_session_data and isinstance(existing_session_data.get("initial_data"), dict):
        prev_content = (existing_session_data["initial_data"].get("content") or "").strip()
        if prev_content and len(prev_content) >= 20:
            msg_lower = message.strip().lower()
            # 平台关键词 + 风格/改写/生成 等 → 视为对上文的改写
            platform_keywords = [
                ("B站", "bilibili", "小破站"), ("小红书", "xiaohongshu"), ("抖音", "douyin"),
                ("微博", "weibo"), ("知乎", "zhihu"),
            ]
            for names in platform_keywords:
                if any(n in message for n in names):
                    if "风格" in message or "改写" in message or "生成" in message or "用" in message:
                        rewrite_previous_for_platform = True
                        rewrite_platform = names[0]  # 用中文展示名
                        session_previous_content = prev_content[:6000]
                        logger.info("frontend/chat: 识别为对上文内容的风格改写, platform=%s, message=%s", rewrite_platform, message.strip()[:80])
                        break

    # 统一路由：全部走策略脑（方案 A）；闲聊由策略脑规划为 casual_reply 后执行
    try:
        # 1. 意图/输入处理（性能优化：极短闲聊跳过意图 LLM，直接进策略脑由快路径处理）
        msg_clean = (message or "").strip()
        if msg_clean in SHORT_CASUAL_REPLIES and len(msg_clean) <= 8:
            processed = {
                "intent": "casual_chat",
                "raw_query": msg_clean,
                "structured_data": {
                    "brand_name": session_intent.get("brand_name", ""),
                    "product_desc": session_intent.get("product_desc", ""),
                    "topic": session_intent.get("topic", ""),
                },
                "explicit_content_request": False,
            }
            logger.info("frontend/chat: 极短闲聊，跳过意图 LLM，直接进策略脑")
        else:
            input_processor = InputProcessor(ai_service=ai)
            processed = await input_processor.process(
                raw_input=message,
                session_id=session_id,
                user_id=user_id,
                conversation_context=conversation_context or None,
                session_document_context=combined_doc_context or None,
            )
        intent = processed.get("intent", "")
        if accepted_suggestion_this_request:
            intent = "creation"
            logger.info("frontend/chat: 用户采纳后续建议，强制走创作路径")
        if rewrite_previous_for_platform:
            intent = "creation"
            logger.info("frontend/chat: 识别为对上文风格改写，强制走创作路径")
        logger.info("frontend/chat: intent=%s (统一走策略脑)", intent)

        if intent == INTENT_COMMAND:
            return JSONResponse(
                content={
                    "success": True,
                    "response": f"命令已识别: /{processed.get('command', '')}",
                    "thinking_process": [],
                    "session_id": session_id,
                    "mode": "creation",
                    "intent": intent,
                    "command": processed.get("command"),
                },
                status_code=status.HTTP_200_OK,
            )

        # 2. 【统一走策略脑】文档查询增强（如适用）
        if intent == INTENT_DOCUMENT_QUERY:
            payload = {
                "processed_input": processed,
                "user_id": user_id,
                "session_id": session_id,
                "enhanced": None,
            }
            try:
                bus = get_plugin_bus()
                event = DocumentQueryEvent.model_construct(source="main", data=payload)
                await bus.publish(event)
                enhanced = payload.get("enhanced")
                if enhanced and isinstance(enhanced, dict):
                    for k, v in enhanced.items():
                        processed[k] = v
            except Exception as e:
                logger.warning("frontend/chat: 文档插件处理异常: %s", e)

        structured = processed.get("structured_data") or {}
        # 合并会话意图：当轮结构化数据优先，空时用会话已存（解决文档/链接轮次丢失主推广对象）
        brand_name = (structured.get("brand_name") or "").strip() or (session_intent.get("brand_name") or "").strip()
        product_desc = (structured.get("product_desc") or "").strip() or (session_intent.get("product_desc") or "").strip()
        topic = (structured.get("topic") or "").strip() or (session_intent.get("topic") or "").strip() or (processed.get("raw_query") or "")
        # 采纳后续建议时：话题只用会话中已有的，不用用户本句（如「可以的」）当作话题，避免「围绕"可以的"」等错误
        if accepted_suggestion_this_request and existing_session_data and isinstance(existing_session_data.get("initial_data"), dict):
            _session_topic = (session_intent.get("topic") or "").strip() or (existing_session_data["initial_data"].get("topic") or "").strip()
            if _session_topic:
                topic = _session_topic
            elif (topic or "").strip() in ("需要", "要", "可以的", "好的", "可以", "试试", "采纳", "行", "好", "嗯"):
                topic = "按上轮建议继续"
        raw_query = (processed.get("raw_query") or "").strip()

        # 参考材料单独解析：从文档/链接中提取对主推广对象的补充，不直接使用原始内容（性能优化：极短闲聊跳过，避免无意义 LLM 调用）
        reference_supplement = ""
        is_short_casual = msg_clean in SHORT_CASUAL_REPLIES and len(msg_clean) <= 8
        if not is_short_casual and combined_doc_context and combined_doc_context.strip():
            main_topic_desc = f"{brand_name or ''} {product_desc or ''}，{topic or ''}".strip() or raw_query[:200]
            if main_topic_desc:
                try:
                    reference_supplement = await extract_reference_supplement(
                        main_topic=main_topic_desc,
                        reference_raw=combined_doc_context,
                        llm_client=ai._llm,
                    )
                    if reference_supplement:
                        logger.info("frontend/chat: 已提取参考材料补充, 长度=%d", len(reference_supplement))
                except Exception as e:
                    logger.warning("frontend/chat: 参考材料补充提取失败: %s", e)

        # 澄清检查：缺基础信息或（明确要生成且缺平台/篇幅）时引导
        if needs_clarification(
            raw_query=raw_query,
            topic=topic,
            product_desc=product_desc,
            brand_name=brand_name,
            intent=intent,
        ):
            summary = product_desc or brand_name or raw_query or message
            clarification = get_clarification_response(
                product_summary=summary,
                brand_name=brand_name,
                product_desc=product_desc,
                topic=topic,
            )
            await _update_session_intent(sm, session_id, brand_name, product_desc, topic, intent, raw_query)
            return JSONResponse(
                content={
                    "success": True,
                    "response": clarification,
                    "thinking_process": [],
                    "session_id": session_id,
                    "mode": "creation",
                    "intent": "clarification",
                },
                status_code=status.HTTP_200_OK,
            )

        # 构建 initial_state 并执行 MetaWorkflow（使用解析后的参考补充，非原始文档/链接）
        user_input_payload = {
            "user_id": user_id,
            "brand_name": brand_name,
            "product_desc": product_desc,
            "topic": topic,
            "tags": request.tags or [],
            "raw_query": processed.get("raw_query"),
            "intent": intent,
            "explicit_content_request": processed.get("explicit_content_request", False),
            "analysis_plugin_result": processed.get("analysis_plugin_result"),
            "conversation_context": conversation_context if conversation_context else None,
            "session_document_context": reference_supplement if reference_supplement else None,
        }
        if accepted_suggestion_this_request and suggested_next_plan_from_session:
            user_input_payload["user_accepted_suggestion"] = True
            user_input_payload["session_suggested_next_plan"] = suggested_next_plan_from_session
            # 采纳的建议若包含 generate，则本轮视为「要求生成内容」，否则策略脑会因 explicit_content_request=false 严禁规划 generate
            if any((s.get("step") or "").lower() == "generate" for s in suggested_next_plan_from_session if isinstance(s, dict)):
                user_input_payload["explicit_content_request"] = True
            # 本轮意图是「采纳建议」，不是字面消息内容：用会话已有话题覆盖 raw_query，避免采纳语被当作话题/搜索词
            user_input_payload["raw_query"] = topic or user_input_payload.get("raw_query") or ""
        if rewrite_previous_for_platform and session_previous_content:
            user_input_payload["rewrite_previous_for_platform"] = True
            user_input_payload["session_previous_content"] = session_previous_content
            user_input_payload["rewrite_platform"] = rewrite_platform
        if has_ambiguous_feedback_after_creation:
            user_input_payload["has_ambiguous_feedback_after_creation"] = True
            user_input_payload["session_suggested_next_plan"] = suggested_next_plan_from_session

        initial_state = {
            "user_input": json.dumps(user_input_payload, ensure_ascii=False),
            "analysis": "",
            "content": "",
            "session_id": session_id,
            "user_id": user_id,
            "evaluation": {},
            "need_revision": False,
            "stage_durations": {},
            "analyze_cache_hit": False,
            "used_tags": [],
            "plan": [],
            "task_type": "",
            "current_step": 0,
            "thinking_logs": [],
            "step_outputs": [],
            "search_context": "",
            "memory_context": "",
            "kb_context": "",
            "effective_tags": [],
            "analysis_plugins": [],
            "generation_plugins": [],
        }
        # 用户采纳后续建议时：只注入上一轮的 analysis，供 generate 沿用（不重新分析）；不注入 thinking_logs，避免汇总重复第一轮整段叙述，保证「接着上文直接生成」的连续性
        if accepted_suggestion_this_request and existing_session_data and isinstance(existing_session_data.get("initial_data"), dict):
            prev = existing_session_data["initial_data"]
            if prev.get("analysis"):
                initial_state["analysis"] = prev["analysis"]
            # 不注入 thinking_logs / step_outputs，本轮只保留「采纳建议 → generate」的简短过程
        # 用户要求「对上文内容改写成 X 风格」时：注入上轮 content 作为改写源，可选注入 analysis 供生成参考
        if rewrite_previous_for_platform and session_previous_content and existing_session_data and isinstance(existing_session_data.get("initial_data"), dict):
            initial_state["content"] = session_previous_content
            prev = existing_session_data["initial_data"]
            if prev.get("analysis"):
                initial_state["analysis"] = prev["analysis"]

        # 执行元工作流（活动策划能力在分析脑/生成脑内，编排层仅按步骤调用）
        meta = build_meta_workflow(
            ai_service=ai,
            knowledge_port=get_knowledge_port(smart_cache) if smart_cache else None,
            metrics={
                "planning": METRIC_PLANNING_DURATION,
                "orchestration": METRIC_ORCHESTRATION_DURATION,
                "compilation": METRIC_COMPILATION_DURATION,
            },
            track_duration=track_duration,
        )

        config = {"configurable": {"thread_id": session_id}}
        if stream:
            async def _stream_events():
                last_chunk = None
                try:
                    async for chunk in meta.astream(initial_state, config=config, stream_mode="values"):
                        try:
                            payload = chunk if isinstance(chunk, dict) else {}
                            last_chunk = payload
                            yield ": keepalive\n"
                            yield f"data: {json.dumps(payload, default=str, ensure_ascii=False)}\n\n"
                        except Exception as e:
                            logger.warning("stream serialize: %s", e)
                    # 流式结束后用最后一帧更新会话，否则 suggested_next_plan 等不会写入，用户下一轮「需要」无法执行建议
                    if last_chunk and isinstance(last_chunk, dict):
                        try:
                            ex = await sm.get_session(session_id)
                            if ex and "initial_data" in ex:
                                upd = ex["initial_data"]
                                so = last_chunk.get("step_outputs") or []
                                last_turn_was_creation = any(
                                    (s.get("step") or "").lower() in ("generate", "evaluate")
                                    for s in so if isinstance(s, dict)
                                )
                                upd.update({
                                    "content": last_chunk.get("content", ""),
                                    "content_sections": last_chunk.get("content_sections") or {},
                                    "analysis": last_chunk.get("analysis", ""),
                                    "evaluation": last_chunk.get("evaluation", {}),
                                    "thinking_logs": last_chunk.get("thinking_logs", []),
                                    "step_outputs": so,
                                    "last_turn_was_creation": last_turn_was_creation,
                                })
                                if last_chunk.get("suggested_next_plan") is not None:
                                    upd["suggested_next_plan"] = last_chunk["suggested_next_plan"]
                                if accepted_suggestion_this_request:
                                    upd["suggested_next_plan"] = None
                                await sm.update_session(session_id, "initial_data", upd)
                                logger.info("frontend/chat: 流式结束已更新会话(含 suggested_next_plan)")
                        except Exception as e:
                            logger.warning("frontend/chat: 流式结束更新会话失败: %s", e)
                except Exception as e:
                    logger.warning("stream error: %s", e)
                    yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            return StreamingResponse(
                _stream_events(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        result = await asyncio.wait_for(
            meta.ainvoke(initial_state, config=config),
            timeout=120.0,
        )

        if result.get("__interrupt__"):
            return JSONResponse(
                content={
                    "success": True,
                    "status": "interrupt",
                    "message": "评估完成，是否修订？请调用 POST /api/v1/chat/resume 传入 session_id 与 human_decision（revise | skip）。",
                    "session_id": session_id,
                    "__interrupt__": result.get("__interrupt__"),
                    "state_snapshot": {k: v for k, v in result.items() if k != "__interrupt__" and not k.startswith("_")},
                },
                status_code=status.HTTP_200_OK,
            )

        thinking_logs = result.get("thinking_logs") or []
        final_content = result.get("content") or ""

        # 更新会话（含 suggested_next_plan 供下一轮采纳；若本轮已采纳则清除）
        try:
            existing_session_data = await sm.get_session(session_id)
            if existing_session_data and "initial_data" in existing_session_data:
                updated_initial_data = existing_session_data["initial_data"]
                step_outputs = result.get("step_outputs") or []
                last_turn_was_creation = any(
                    (s.get("step") or "").lower() in ("generate", "evaluate")
                    for s in step_outputs if isinstance(s, dict)
                )
                updated_initial_data.update({
                    "content": final_content,
                    "content_sections": result.get("content_sections") or {},
                    "analysis": result.get("analysis", ""),
                    "evaluation": result.get("evaluation", {}),
                    "thinking_logs": thinking_logs,
                    "step_outputs": step_outputs,
                    "last_turn_was_creation": last_turn_was_creation,
                })
                if result.get("suggested_next_plan") is not None:
                    updated_initial_data["suggested_next_plan"] = result.get("suggested_next_plan")
                if accepted_suggestion_this_request:
                    updated_initial_data["suggested_next_plan"] = None
                await sm.update_session(session_id, "initial_data", updated_initial_data)
        except Exception as e:
            logger.warning("frontend/chat: 更新会话失败: %s", e)

        await _update_session_intent(sm, session_id, brand_name, product_desc, topic, intent, raw_query)

        # P0/P1: 创作成功后异步提炼标签并回写 profile
        if request.tags and len(request.tags) > 0:
            pass  # 用户显式传了 tags，不覆盖
        else:
            asyncio.create_task(_derive_and_update_tags_background(
                user_id=user_id,
                topic=topic,
                brand_name=brand_name,
                product_desc=product_desc,
                raw_query=raw_query,
                content_preview=(final_content or "")[:400],
                ai_svc=ai,
                sm=sm,
            ))

        # 保存交互历史
        try:
            history = InteractionHistory(
                user_id=user_id,
                session_id=session_id,
                user_input=json.dumps(
                    {"message": message, "intent": intent, "topic": topic},
                    ensure_ascii=False,
                ),
                ai_output=final_content,
            )
            db.add(history)
            await db.commit()
        except Exception as e:
            logger.warning("frontend/chat: 创作保存历史失败: %s", e)
            try:
                await db.rollback()
            except Exception:
                pass

        logger.info("frontend/chat: 创作完成, session_id=%s", session_id)

        content_sections = result.get("content_sections") or {}
        return JSONResponse(
            content={
                "success": True,
                "response": final_content,
                "thinking_process": thinking_logs,
                "content_sections": content_sections,
                "session_id": session_id,
                "mode": "creation",
                "intent": intent,
            },
            status_code=status.HTTP_200_OK,
        )

    except asyncio.TimeoutError:
        logger.warning("frontend/chat: 创作超时, session_id=%s", session_id)
        return JSONResponse(
            content={
                "success": False,
                "error": "创作超时，请稍后重试。",
            },
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except Exception as e:
        logger.exception("frontend/chat: 创作执行失败")
        try:
            await db.rollback()
        except Exception:
            pass
        return JSONResponse(
            content={
                "success": False,
                "error": "创作失败，请稍后重试。",
                "detail": str(e),
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@app.post(
    "/api/v1/chat/resume",
    summary="人工介入恢复",
    description="在评估后中断时，传入 human_decision（revise | skip）从断点继续执行。session_id 须与中断时一致（即 thread_id）。",
    tags=["前端"],
)
async def chat_resume(
    body: ChatResumeRequest,
    ai: SimpleAIService = Depends(get_ai_service),
) -> JSONResponse:
    """从人工决策断点恢复：Command(resume=human_decision)，同一 thread_id 继续。"""
    if Command is None:
        return JSONResponse(
            content={"success": False, "error": "LangGraph Command 未可用，无法恢复。"},
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
        )
    session_id = (body.session_id or "").strip()
    if not session_id:
        return JSONResponse(
            content={"success": False, "error": "session_id 必填。"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    human_decision = (body.human_decision or "").strip().lower()
    if human_decision not in ("revise", "skip"):
        human_decision = "revise" if human_decision in ("true", "1", "yes") else "skip"
    config = {"configurable": {"thread_id": session_id}}
    meta = build_meta_workflow(
        ai_service=ai,
        knowledge_port=get_knowledge_port(smart_cache) if smart_cache else None,
    )
    try:
        result = await asyncio.wait_for(
            meta.ainvoke(Command(resume=human_decision), config=config),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            content={"success": False, "error": "恢复执行超时。", "session_id": session_id},
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except Exception as e:
        logger.warning("chat/resume 失败: %s", e, exc_info=True)
        return JSONResponse(
            content={"success": False, "error": "恢复执行失败。", "detail": str(e), "session_id": session_id},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if result.get("__interrupt__"):
        return JSONResponse(
            content={
                "success": True,
                "status": "interrupt",
                "message": "再次等待人工决策。",
                "session_id": session_id,
                "__interrupt__": result.get("__interrupt__"),
                "state_snapshot": {k: v for k, v in result.items() if k != "__interrupt__" and not k.startswith("_")},
            },
            status_code=status.HTTP_200_OK,
        )
    thinking_logs = result.get("thinking_logs") or []
    final_content = result.get("content") or ""
    content_sections = result.get("content_sections") or {}
    return JSONResponse(
        content={
            "success": True,
            "response": final_content,
            "thinking_process": thinking_logs,
            "content_sections": content_sections,
            "session_id": session_id,
            "status": "completed",
        },
        status_code=status.HTTP_200_OK,
    )


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


MAX_DOCS_PER_SESSION = 5  # 每个会话最多附加 5 个文档


@app.post(
    "/api/v1/documents/upload",
    summary="上传文档（绑定到会话）",
    description="上传文件并绑定到当前会话。每次上传 1 个文件，每个会话最多 5 个。存储到 uploads/{user_id}/，元信息入库，并关联 session_documents 表。",
    tags=["文档"],
)
async def documents_upload(
    file: UploadFile = File(..., description="上传文件（每次 1 个）"),
    user_id: str = Form(..., description="用户唯一标识"),
    session_id: str = Form(..., description="会话 ID，文档将绑定到该会话"),
    doc_binding: SessionDocumentBinding = Depends(get_session_document_binding),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """上传文档并绑定到会话：每次 1 个，每会话最多 5 个。"""
    if not session_id or not session_id.strip():
        return JSONResponse(
            content={"success": False, "error": "session_id 必填，文档将绑定到当前会话"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    existing = await doc_binding.list_by_session(session_id.strip())
    if len(existing) >= MAX_DOCS_PER_SESSION:
        return JSONResponse(
            content={"success": False, "error": f"当前会话最多上传 {MAX_DOCS_PER_SESSION} 个文档，已达上限"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    fn = (file.filename or "").strip()
    if fn and "." in fn:
        ext = fn.rsplit(".", 1)[-1].lower()
        if ext not in SUPPORTED_DOC_EXTENSIONS:
            return JSONResponse(
                content={
                    "success": False,
                    "error": f"不支持的文件类型 .{ext}，支持：PDF、TXT、MD、DOCX、PPTX、图片(jpg/png/gif/webp/bmp/tiff)",
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    try:
        content = await file.read()
        doc = await doc_binding.attach(
            file_content=content,
            filename=file.filename or "unnamed",
            user_id=user_id,
            session_id=session_id.strip(),
        )
        await db.commit()
        return JSONResponse(
            content={
                "success": True,
                "data": doc.model_dump(mode="json"),
            },
            status_code=status.HTTP_200_OK,
        )
    except ValueError as e:
        await db.rollback()
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        await db.rollback()
        logger.error("documents/upload 出错: %s", e, exc_info=True)
        raise


@app.get(
    "/api/v1/documents",
    summary="列出文档",
    description="按 session_id 列出当前会话附加的文档；或按 user_id 列出该用户全部文档（兼容旧接口）。优先使用 session_id。",
    tags=["文档"],
)
async def documents_list(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    doc_binding: SessionDocumentBinding = Depends(get_session_document_binding),
    doc_svc: DocumentService = Depends(get_document_service),
) -> JSONResponse:
    """列出文档：session_id 时返回会话附加文档；否则按 user_id 返回用户全部文档。"""
    try:
        if session_id and session_id.strip():
            items = await doc_binding.list_by_session(session_id.strip())
        elif user_id and user_id.strip():
            items = await doc_svc.list_by_user(user_id.strip())
        else:
            return JSONResponse(
                content={"success": False, "error": "请提供 session_id 或 user_id"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return JSONResponse(
            content={
                "success": True,
                "data": [d.model_dump(mode="json") for d in items],
            },
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error("documents/list 出错: %s", e, exc_info=True)
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
            "analyze_deep": "/api/v1/analyze-deep (POST)",
            "analyze_deep_raw": "/api/v1/analyze-deep/raw (POST)",
            "chat_new": "/api/v1/chat/new (POST)",
            "documents_upload": "/api/v1/documents/upload (POST)",
            "documents_list": "/api/v1/documents (GET)",
            "feedback": "/api/v1/feedback (POST)",
            "frontend_session_init": "/api/v1/frontend/session/init (GET)",
            "frontend_chat": "/api/v1/frontend/chat (POST)"
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
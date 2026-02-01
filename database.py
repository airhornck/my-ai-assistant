import os
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship


# ---------------------------------------------------------------------------
# Base 类定义（SQLAlchemy 2.0+ 规范）
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """声明式基类，所有模型继承此类（SQLAlchemy 2.0+ 规范）"""
    pass


# ---------------------------------------------------------------------------
# 数据库连接引擎与会话（完全异步模式）
# ---------------------------------------------------------------------------

def _convert_to_async_url(database_url: str) -> str:
    """
    将同步 PostgreSQL URL 转换为异步 URL（postgresql+asyncpg://）。
    
    确保连接字符串以 postgresql+asyncpg:// 开头，以使用 asyncpg 驱动。
    
    Args:
        database_url: 原始数据库URL（如 postgresql://...）
        
    Returns:
        异步数据库URL（postgresql+asyncpg://...）
    """
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql+asyncpg://"):
        return database_url
    else:
        raise ValueError(f"不支持的数据库URL格式: {database_url}")


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/ai_assistant"
)

# 转换为异步URL（确保使用 asyncpg 驱动）
ASYNC_DATABASE_URL = _convert_to_async_url(DATABASE_URL)

# 连接池：生产环境建议起始值 pool_size=20、max_overflow=40；最优值需结合 ECS 内存、PostgreSQL max_connections 与压测确定
# 务必保证 (pool_size + max_overflow) < PostgreSQL max_connections（为系统预留连接）；连接池过大会增加客户端内存
_DEFAULT_POOL_SIZE = 20
_DEFAULT_MAX_OVERFLOW = 40
_DEFAULT_POOL_RECYCLE = 3600  # 秒，连接回收前存活时长，可防止数据库端连接超时


def _int_env(name: str, default: int) -> int:
    try:
        val = os.getenv(name)
        return int(val) if val is not None and val.strip() else default
    except ValueError:
        return default


POOL_SIZE = _int_env("DATABASE_POOL_SIZE", _DEFAULT_POOL_SIZE)
MAX_OVERFLOW = _int_env("DATABASE_MAX_OVERFLOW", _DEFAULT_MAX_OVERFLOW)
POOL_RECYCLE = _int_env("DATABASE_POOL_RECYCLE", _DEFAULT_POOL_RECYCLE)

# 创建异步引擎（SQLAlchemy 2.0+ 规范）
engine: AsyncEngine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,
    echo=False,
)

# 创建异步会话工厂（SQLAlchemy 2.0+ 规范）
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话，用于依赖注入（SQLAlchemy 2.0+ 异步规范）。
    
    使用 async with 管理会话生命周期，确保资源正确释放。
    
    Yields:
        AsyncSession: 异步数据库会话
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# ORM 模型（继承自 DeclarativeBase）
# ---------------------------------------------------------------------------


class UserProfile(Base):
    """用户画像表。与 InteractionHistory 为一对多关联（一个用户多条交互记录）。"""

    __tablename__ = "user_profiles"

    user_id = Column(String(64), primary_key=True, index=True)  # 主键，非空
    brand_name = Column(String(256), nullable=True)
    industry = Column(String(128), nullable=True)
    preferred_style = Column(String(256), nullable=True)
    # 兴趣标签列表（JSON 存储），由记忆优化服务写入。若表已存在需手动 ALTER 或重建表
    tags = Column(JSON, nullable=True, default=None, comment="兴趣标签列表，如 [\"科技数码\",\"偏爱简洁文案\"]")
    # 品牌事实库（JSON 存储），如 [{"fact": "...", "category": "..."}]
    brand_facts = Column(JSON, nullable=True, default=None, comment="品牌事实库")
    # 成功案例库（JSON 存储），如 [{"title": "...", "description": "...", "outcome": "..."}]
    success_cases = Column(JSON, nullable=True, default=None, comment="成功案例库")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关联：UserProfile 1 -> N InteractionHistory（back_populates 双向绑定）
    interactions = relationship("InteractionHistory", back_populates="user_profile")


class InteractionHistory(Base):
    """交互历史表。多对一关联 UserProfile（多条记录属于同一用户）。"""

    __tablename__ = "interaction_histories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String(64),
        ForeignKey("user_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = Column(String(128), nullable=False, index=True)
    user_input = Column(Text, nullable=True)
    ai_output = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_rating = Column(Integer, nullable=True, comment="用户评分，如 1-5")
    user_comment = Column(Text, nullable=True, comment="用户文字反馈")

    # 关联：N InteractionHistory -> 1 UserProfile（back_populates 双向绑定）
    user_profile = relationship("UserProfile", back_populates="interactions")


# ---------------------------------------------------------------------------
# 数据库初始化与工具函数（异步模式）
# ---------------------------------------------------------------------------


async def create_tables(engine: AsyncEngine) -> None:
    """
    在应用启动时创建所有表（异步模式，SQLAlchemy 2.0+ 规范）。
    
    Args:
        engine: 异步数据库引擎
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user_profile(db: AsyncSession, user_id: str) -> UserProfile:
    """
    按 user_id 获取用户档案；若不存在则创建一条基础档案并返回（异步模式）。
    
    使用 SQLAlchemy 2.0+ 的 select() 语法进行查询。

    Args:
        db: 异步 SQLAlchemy 会话
        user_id: 用户唯一标识

    Returns:
        已存在的或新建的 UserProfile 实例
    """
    from sqlalchemy import select
    
    # 使用 select 语句查询（SQLAlchemy 2.0+ 异步规范）
    result = await db.execute(select(UserProfile).filter(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    
    if profile is not None:
        return profile
    
    # 创建新档案
    profile = UserProfile(user_id=user_id)
    db.add(profile)
    await db.flush()
    return profile


# 注：Document、SessionDocument 等模型需在 create_tables 前被导入以注册表结构。
# 在 main.py lifespan 中导入：import models.document  # noqa: F401

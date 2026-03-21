"""
供路由层获取全局服务实例的依赖（避免 main 与 routers 循环引用）。
在 lifespan 中由 main 设置 _ai_service_ref、_memory_service_ref，能力接口等路由通过 get_*_for_router 注入。
"""
from __future__ import annotations

from typing import Any, AsyncGenerator

_ai_service_ref: Any = None
_memory_service_ref: Any = None


def set_ai_service(service: Any) -> None:
    """由 main lifespan 调用，注入 AI 服务实例。"""
    global _ai_service_ref
    _ai_service_ref = service


def set_memory_service(service: Any) -> None:
    """由 main lifespan 调用，注入 MemoryService 实例（用户画像、记忆）。"""
    global _memory_service_ref
    _memory_service_ref = service


async def get_ai_service_for_router() -> AsyncGenerator[Any, None]:
    """供 capability_api 等路由使用的 AI 服务依赖。"""
    if _ai_service_ref is None:
        raise RuntimeError("AI 服务未初始化")
    yield _ai_service_ref


async def get_memory_service_for_router() -> AsyncGenerator[Any, None]:
    """供 capability_api 等路由使用的 MemoryService 依赖；未设置时 yield None（能力接口可降级）。"""
    yield _memory_service_ref

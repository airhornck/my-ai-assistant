"""
插件总线：系统“中枢神经系统”，负责插件间消息传递。
事件驱动：发布事件后，所有 can_handle 为 True 的插件依次异步处理；
返回值可作为新事件再次发布，形成处理链。单个插件异常不影响总线与其他插件。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 基础事件（Pydantic）
# ---------------------------------------------------------------------------


class PluginEvent(BaseModel):
    """插件总线基础事件。"""

    event_type: str = Field(..., description="事件类型，用于路由与订阅")
    source: str = Field(default="", description="事件来源（插件名或系统组件）")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="事件发生时间",
    )
    data: Optional[Dict[str, Any]] = Field(default=None, description="事件载荷")

    class Config:
        arbitrary_types_allowed = True

    def to_follow_up(self, new_type: str, new_data: Optional[Dict[str, Any]] = None) -> "PluginEvent":
        """基于当前事件生成后续事件（保留 source 等，便于链路追踪）。"""
        return PluginEvent(
            event_type=new_type,
            source=self.source,
            timestamp=datetime.now(timezone.utc),
            data=new_data or self.data,
        )


# ---------------------------------------------------------------------------
# 系统级预置事件（后续插件可订阅）
# ---------------------------------------------------------------------------


# 文档上传完成：data 可含 doc_id, user_id, storage_path 等
DOCUMENT_UPLOADED = "document_uploaded"


# 用户输入涉及文档查询：data 含 processed_input、user_id、session_id；插件可写回 enhanced 增强 ProcessedInput
DOCUMENT_QUERY = "document_query"


class DocumentQueryEvent(PluginEvent):
    """文档查询事件。主流程在识别到 document_query 意图时发布；文档插件可补全/增强 data.processed_input 并写回 data.enhanced。"""

    event_type: str = Field(default=DOCUMENT_QUERY, description="固定为 document_query")
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="含 processed_input、user_id、session_id；插件可写回 enhanced（增强后的 ProcessedInput 片段）",
    )


class DocumentUploadedEvent(PluginEvent):
    """文档上传完成事件。文档解析插件可订阅此事件。"""

    event_type: str = Field(default=DOCUMENT_UPLOADED, description="固定为 document_uploaded")
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="如 doc_id, user_id, storage_path, filename 等",
    )


# 意图识别完成：data 可含 intent, processed_input 等
INTENT_RECOGNIZED = "intent_recognized"


class IntentRecognizedEvent(PluginEvent):
    """意图识别完成事件。"""

    event_type: str = Field(default=INTENT_RECOGNIZED, description="固定为 intent_recognized")
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="如 intent, processed_input, raw_query 等",
    )


# 分析/工作流完成：data 可含 content, thinking_logs, session_id 等
ANALYSIS_COMPLETED = "analysis_completed"


class AnalysisCompletedEvent(PluginEvent):
    """分析/元工作流完成事件。"""

    event_type: str = Field(default=ANALYSIS_COMPLETED, description="固定为 analysis_completed")
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="如 content, thinking_logs, session_id 等",
    )


# ---------------------------------------------------------------------------
# 插件抽象基类
# ---------------------------------------------------------------------------


class BasePlugin(ABC):
    """
    插件抽象基类：所有接入总线的插件必须实现 can_handle 与 handle（均为异步）。
    """

    @abstractmethod
    async def can_handle(self, event: PluginEvent) -> bool:
        """是否处理该事件。"""
        ...

    @abstractmethod
    async def handle(self, event: PluginEvent) -> Optional[PluginEvent]:
        """
        处理事件。返回值若非 None，将作为新事件再次发布到总线，形成处理链。
        """
        ...


# ---------------------------------------------------------------------------
# 插件总线
# ---------------------------------------------------------------------------


class PluginBus:
    """
    插件总线：维护插件列表，发布事件时按序调用所有 can_handle 为 True 的插件的 handle；
    返回值作为新事件再次发布。单个插件异常仅记录日志，不中断总线与其他插件。
    """

    def __init__(self) -> None:
        self._plugins: List[BasePlugin] = []

    async def register(self, plugin: BasePlugin) -> None:
        """注册一个插件。"""
        if plugin is not None and plugin not in self._plugins:
            self._plugins.append(plugin)
            logger.debug("PluginBus: 已注册插件 %s", getattr(plugin, "__class__", {}).__name__)

    def unregister(self, plugin: BasePlugin) -> None:
        """从总线移除插件。"""
        if plugin in self._plugins:
            self._plugins.remove(plugin)

    async def publish(self, event: PluginEvent, _chain_depth: int = 0) -> None:
        """
        发布事件：对所有 can_handle(event) 为 True 的插件依次调用 handle(event)。
        handle 返回的非 None 事件会再次调用 publish，形成处理链。
        任一插件抛出异常时仅记录日志并继续执行其余插件（错误隔离）。
        _chain_depth 用于限制递归深度，防止无限链。
        """
        if event is None:
            return
        max_depth = 32
        if _chain_depth >= max_depth:
            logger.warning("PluginBus: 处理链深度已达 %s，停止继续发布", max_depth)
            return
        for plugin in list(self._plugins):
            try:
                can = await plugin.can_handle(event)
            except Exception as e:
                logger.warning(
                    "PluginBus: 插件 %s can_handle 异常，已跳过: %s",
                    getattr(plugin, "__class__", {}).__name__,
                    e,
                    exc_info=True,
                )
                continue
            if not can:
                continue
            try:
                result = await plugin.handle(event)
                if result is not None and isinstance(result, PluginEvent):
                    await self.publish(result, _chain_depth=_chain_depth + 1)
            except Exception as e:
                logger.warning(
                    "PluginBus: 插件 %s handle 异常，已跳过: %s",
                    getattr(plugin, "__class__", {}).__name__,
                    e,
                    exc_info=True,
                )


_bus: Optional[PluginBus] = None


def get_plugin_bus() -> PluginBus:
    """获取插件总线单例。"""
    global _bus
    if _bus is None:
        _bus = PluginBus()
    return _bus

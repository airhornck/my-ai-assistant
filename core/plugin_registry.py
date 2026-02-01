"""
插件注册中心：单例，在应用启动时(lifespan)初始化。
提供 register_workflow(name, workflow_builder_func) 与 get_workflow(name)。
插件加载失败时仅记录日志，不影响主流程。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 插件规范：build_workflow(config) -> 符合 LangGraph 的 CompiledGraph，支持 .ainvoke(state)


class PluginRegistry:
    """单例：工作流插件注册中心。"""

    _instance: PluginRegistry | None = None
    _builders: dict[str, Callable[..., Any]]  # name -> build_workflow(config) -> CompiledGraph
    _compiled: dict[str, Any]  # name -> CompiledGraph（init_plugins 后填充）

    def __new__(cls) -> PluginRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._builders = {}
            cls._instance._compiled = {}
        return cls._instance

    def register_workflow(self, name: str, workflow_builder_func: Callable[..., Any]) -> None:
        """
        注册工作流构建函数。不在此处编译，由 init_plugins(config) 统一编译。
        workflow_builder_func(config) 应返回 LangGraph CompiledGraph（支持 .ainvoke(state)）。
        """
        if not name or not callable(workflow_builder_func):
            logger.warning("PluginRegistry: 忽略无效注册 name=%r", name)
            return
        self._builders[name] = workflow_builder_func
        logger.debug("PluginRegistry: 已注册构建函数 name=%s", name)

    def init_plugins(self, config: dict[str, Any] | None = None) -> None:
        """
        使用给定 config 调用所有已注册的构建函数，生成 CompiledGraph 并缓存。
        某个插件构建失败时仅记录警告并跳过，不影响其他插件。
        """
        config = config or {}
        self._compiled.clear()
        for name, builder in list(self._builders.items()):
            try:
                graph = builder(config)
                if graph is not None and callable(getattr(graph, "ainvoke", None)):
                    self._compiled[name] = graph
                    logger.info("PluginRegistry: 已加载插件 name=%s", name)
                else:
                    logger.warning("PluginRegistry: 插件 %s 未返回有效的 CompiledGraph，已跳过", name)
            except Exception as e:
                logger.warning("PluginRegistry: 插件 %s 加载失败，已跳过: %s", name, e, exc_info=True)

    def get_workflow(self, name: str) -> Any | None:
        """
        根据名称获取已编译的工作流。若未找到则返回 None（调用方需降级处理）。
        """
        return self._compiled.get(name)

    def list_workflow_names(self) -> list[str]:
        """返回当前已成功加载的工作流名称列表。"""
        return list(self._compiled.keys())


def get_registry() -> PluginRegistry:
    """获取 PluginRegistry 单例。"""
    return PluginRegistry()

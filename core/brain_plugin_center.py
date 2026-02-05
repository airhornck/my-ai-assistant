"""
脑级插件中心：各脑（分析脑、生成脑等）的插件统一管理。
插件是对脑的能力补充，只注册在所属脑中。

插件类型：
- 定时插件 (scheduled)：周期刷新，结果缓存，调用时读缓存；每插件单独配置 schedule_config
- 实时插件 (realtime)：按需执行，每次调用都运行
- 工作流插件 (workflow)：多步骤工作流，可为定时或实时
- 技能插件 (skill)：单一能力/工具，通常为实时
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# 插件类型常量
PLUGIN_TYPE_SCHEDULED = "scheduled"   # 定时插件
PLUGIN_TYPE_REALTIME = "realtime"     # 实时插件
PLUGIN_TYPE_WORKFLOW = "workflow"     # 工作流插件
PLUGIN_TYPE_SKILL = "skill"           # 技能插件

PLUGIN_TYPES = (PLUGIN_TYPE_SCHEDULED, PLUGIN_TYPE_REALTIME, PLUGIN_TYPE_WORKFLOW, PLUGIN_TYPE_SKILL)

# 各脑已注册插件清单（供加载时遍历，实现注册可见性）
# 格式：脑名 -> [(插件模块路径, 插件内 register 函数名)]
# 规划脑只登记「拼装后」或「无需拼装」的插件；拼装逻辑在插件中心内完成（campaign_context 内调 methodology/case_library/knowledge_base）
ANALYSIS_BRAIN_PLUGINS = [
    ("plugins.bilibili_hotspot.plugin", "register"),
    ("plugins.methodology.plugin", "register"),
    ("plugins.case_library.plugin", "register"),
    ("plugins.knowledge_base.plugin", "register"),
    ("plugins.campaign_context.plugin", "register"),  # 拼装插件，供规划脑登记
]
# 文本/活动方案/图片/视频/PPT 等均以插件方式登记；模型配置由插件中心 config 管理；未来可扩展 ppt_generator 等
GENERATION_BRAIN_PLUGINS: list[tuple[str, str]] = [
    ("plugins.text_generator.plugin", "register"),
    ("plugins.campaign_plan_generator.plugin", "register"),
    ("plugins.image_generator.plugin", "register"),
    ("plugins.video_generator.plugin", "register"),
    # 未来：("plugins.ppt_generator.plugin", "register"),
]
STRATEGY_BRAIN_PLUGINS: list[tuple[str, str]] = []


class BrainPluginCenter:
    """
    脑级插件管理中心。
    负责插件的注册、定时任务的调度、以及按类型获取插件输出。
    """

    def __init__(self, brain_name: str, config: dict[str, Any] | None = None) -> None:
        """
        Args:
            brain_name: 所属脑的名称（如 analysis、generation）
            config: 全局配置（cache、ai_service 等），供插件使用
        """
        self._brain_name = brain_name
        self._config = config or {}
        self._plugins: dict[str, dict[str, Any]] = {}  # name -> {type, config, ...}
        self._scheduler = None

    def register_plugin(
        self,
        name: str,
        plugin_type: str,
        *,
        get_output: Callable[[str, dict], Awaitable[dict[str, Any]]] | None = None,
        refresh_func: Callable[[], Awaitable[Any]] | None = None,
        schedule_config: dict[str, Any] | None = None,
        refresh_interval_hours: float | None = None,
    ) -> None:
        """
        注册插件。

        Args:
            name: 插件名称
            plugin_type: PLUGIN_TYPE_SCHEDULED / REALTIME / WORKFLOW / SKILL
            get_output: 获取插件输出。签名 (name, context) -> dict
            refresh_func: 定时插件的刷新函数（仅 scheduled 需要）
            schedule_config: 定时插件**单独**的定时配置，如 {"interval_hours": 6}；不使用统一配置
            refresh_interval_hours: 兼容旧参数，等同 schedule_config={"interval_hours": v}；与 schedule_config 同时存在时 schedule_config 优先
        """
        if plugin_type not in PLUGIN_TYPES:
            logger.warning("未知插件类型 %s，将按 realtime 处理", plugin_type)
        sc = dict(schedule_config or {})
        if refresh_interval_hours is not None and "interval_hours" not in sc:
            sc["interval_hours"] = refresh_interval_hours
        if plugin_type == PLUGIN_TYPE_SCHEDULED and "interval_hours" not in sc:
            sc["interval_hours"] = 6
        self._plugins[name] = {
            "type": plugin_type,
            "get_output": get_output,
            "refresh_func": refresh_func,
            "schedule_config": sc,
        }
        logger.info("脑级插件中心 [%s] 已注册插件: %s (类型=%s)", self._brain_name, name, plugin_type)

    def start_scheduled_tasks(self) -> None:
        """启动定时插件的刷新任务。"""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
        except ImportError:
            logger.warning("APScheduler 未安装，定时插件将不运行")
            return

        scheduled = [n for n, p in self._plugins.items() if p["type"] == PLUGIN_TYPE_SCHEDULED and p.get("refresh_func")]
        if not scheduled:
            return

        self._scheduler = AsyncIOScheduler()

        async def _run_refresh(func: Callable) -> None:
            try:
                result = func()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning("定时插件刷新失败: %s", e, exc_info=True)

        for name in scheduled:
            plugin = self._plugins[name]
            func = plugin["refresh_func"]
            sc = plugin.get("schedule_config") or {}
            interval = sc.get("interval_hours", 6)

            def _make_job(f: Callable) -> Callable:
                def job():
                    asyncio.create_task(_run_refresh(f))
                return job

            self._scheduler.add_job(
                _make_job(func),
                "interval",
                hours=interval,
                id=f"{self._brain_name}_{name}",
            )
            # 不在此处立即执行，改由 run_initial_refresh() 在 lifespan 完全就绪后调用

        self._scheduler.start()
        logger.info("脑级插件中心 [%s] 定时任务已启动: %s", self._brain_name, scheduled)

    def run_initial_refresh(self) -> None:
        """
        在应用完全启动后执行各定时插件的首次刷新。
        应在 lifespan 就绪后调用，避免过早执行导致 env/config 未就绪。
        """
        scheduled = [n for n, p in self._plugins.items() if p["type"] == PLUGIN_TYPE_SCHEDULED and p.get("refresh_func")]
        for name in scheduled:
            plugin = self._plugins[name]
            func = plugin["refresh_func"]

            async def _run(plugin_name: str, refresh_fn: Any) -> None:
                try:
                    result = refresh_fn()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.warning("定时插件 %s 首次刷新失败: %s", plugin_name, e, exc_info=True)

            asyncio.create_task(_run(name, func))

    def stop_scheduled_tasks(self) -> None:
        """停止定时任务。"""
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception as e:
                logger.debug("停止定时任务时出错: %s", e)
            self._scheduler = None

    async def get_output(self, plugin_name: str, context: dict) -> dict[str, Any]:
        """
        获取插件输出。

        Args:
            plugin_name: 插件名称
            context: 调用上下文（如 user_input、analysis 等）

        Returns:
            插件输出，通常为 {"analysis": {...}} 或类似结构，供编排层合并
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            return {}

        get_output_fn = plugin.get("get_output")
        if get_output_fn is None:
            return {}

        try:
            return await get_output_fn(plugin_name, context)
        except Exception as e:
            logger.warning("插件 %s 获取输出失败: %s", plugin_name, e, exc_info=True)
            return {}

    def has_plugin(self, plugin_name: str) -> bool:
        """检查是否已注册该插件。"""
        return plugin_name in self._plugins

    def list_plugins(self) -> list[str]:
        """返回已注册插件名称列表。"""
        return list(self._plugins.keys())

    @staticmethod
    def load_plugins_for_brain(
        brain_name: str,
        plugin_center: "BrainPluginCenter",
        config: dict[str, Any],
        plugin_list: list[tuple[str, str]],
    ) -> None:
        """
        根据插件清单加载并注册插件。

        Args:
            brain_name: 脑名称（用于日志）
            plugin_center: 插件中心实例
            config: 传给各插件 register 的配置
            plugin_list: [(模块路径, 函数名), ...]，如 [("plugins.bilibili_hotspot.plugin", "register")]
        """
        for module_path, func_name in plugin_list:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                register_fn = getattr(mod, func_name, None)
                if callable(register_fn):
                    register_fn(plugin_center, config)
                else:
                    logger.warning("插件 %s 中未找到可调用的 %s", module_path, func_name)
            except Exception as e:
                logger.warning("加载插件 %s.%s 失败: %s", module_path, func_name, e, exc_info=True)

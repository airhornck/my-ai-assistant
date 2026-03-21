"""
脑级插件开发模板 (Brain Plugin Template)
=========================================

插件开发仅需两步：1) 开发插件  2) 注册插件。无需改应用启动逻辑，数据库、定时任务等均由参数化注入。

【两步开发流程】
1. 开发插件：复制本文件到 `plugins/你的插件名/plugin.py`，实现 `register(plugin_center, config)`，
   在 register 内从 config 获取依赖并实现 get_output（及可选 refresh_func），最后调用
   plugin_center.register_plugin(...)。
2. 注册插件：在 `core/brain_plugin_center.py` 的 `ANALYSIS_BRAIN_PLUGINS` 或 `GENERATION_BRAIN_PLUGINS`
   中添加一行：("plugins.你的插件名.plugin", "register")。

【参数化依赖：禁止在插件内直接 import】
以下能力均通过 register 的 config 参数注入，插件内不得 from database import ...、import apscheduler 等：

| config 键名              | 说明                     | 用法示例 |
|--------------------------|--------------------------|----------|
| ai_service               | AI 服务（分析/生成/路由）| config.get("ai_service") |
| cache / smart_cache      | 缓存（读写热点/中间结果）| config.get("cache")，定时插件写缓存 |
| memory_service           | 记忆服务（用户画像/记忆条）| config.get("memory_service") |
| db_session_factory      | 数据库会话工厂（异步）   | async with config["db_session_factory"]() as session: ...
| plugin_bus              | 事件总线                 | config.get("plugin_bus") or get_plugin_bus()
| 定时任务                 | 不直接使用 scheduler    | 将刷新逻辑写成 async def refresh(): ...，通过 register_plugin(..., refresh_func=refresh, schedule_config={"interval_hours": 6}) 注册，由插件中心统一调度 |

【插件类型】
- realtime：每次调用时执行 get_output。
- scheduled：由中心按 schedule_config 定时执行 refresh_func，get_output 仅读缓存。
"""
from __future__ import annotations

import logging
import json
from typing import Any, Dict, Optional

# 引入核心依赖
from core.brain_plugin_center import (
    BrainPluginCenter, 
    PLUGIN_TYPE_REALTIME, 
    PLUGIN_TYPE_SCHEDULED
)
# 如果需要调用 LLM
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------
PLUGIN_NAME = "my_awesome_plugin"  # TODO: 修改插件名称 (唯一标识)
CACHE_KEY_PREFIX = f"{PLUGIN_NAME}:data"

def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """
    插件注册入口。所有依赖仅从 config 获取，禁止在插件内 import database / apscheduler 等。
    """
    # 1. 从 config 参数化获取依赖（由应用启动时注入）
    ai_service = config.get("ai_service")
    cache = config.get("cache") or config.get("smart_cache")
    memory_service = config.get("memory_service")
    db_session_factory = config.get("db_session_factory")  # 需写 DB 时：async with db_session_factory() as session

    # -----------------------------------------------------------------------
    # 模式 A: 实时处理模式 (Realtime)
    # 适用于：依赖当前 Context 进行实时分析、生成、决策的场景。
    # -----------------------------------------------------------------------
    async def get_output_realtime(_name: str, context: dict) -> dict[str, Any]:
        """
        实时逻辑核心函数。
        
        Args:
            _name: 插件名称
            context: 当前请求的上下文，通常包含:
                     - "request": 用户请求对象或字典
                     - "analysis": 分析脑已有的分析结果
                     - "preference_context": 用户偏好 (如有)
        
        Returns:
            dict: 返回的数据将合并到 Context 中 (通常建议放在 analysis 或 specific key 下)
        """
        if not ai_service:
            logger.warning(f"[{PLUGIN_NAME}] 缺少 AI Service，跳过执行")
            return {}

        # 示例：从 Context 获取输入
        request = context.get("request")
        user_input = getattr(request, "user_input", "") if request else ""

        # 示例：调用 AI 模型
        # available models: fast_model (gpt-4o-mini/flash), powerful_model (gpt-4o/pro)
        llm = ai_service.router.fast_model 
        
        try:
            # 模拟业务逻辑
            prompt = f"请分析以下内容的情感倾向：{user_input}"
            # response = await llm.ainvoke([HumanMessage(content=prompt)])
            # result = response.content
            result = "模拟的分析结果" # TODO: 替换为真实逻辑

            logger.info(f"[{PLUGIN_NAME}] 实时执行完成")
            
            # 返回结果，通常建议包裹在插件名 key 下，防止污染根 Context
            return {
                "analysis": {
                    **context.get("analysis", {}),
                    PLUGIN_NAME: {
                        "sentiment": result,
                        "timestamp": "now"
                    }
                }
            }
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 执行出错: {e}", exc_info=True)
            return {}

    # -----------------------------------------------------------------------
    # 模式 B: 定时任务模式 (Scheduled)
    # 定时由插件中心统一调度，插件只提供 refresh_func，禁止在插件内使用 apscheduler。
    # -----------------------------------------------------------------------
    async def refresh() -> None:
        """定时任务回调：由中心按 schedule_config 调用，插件内只写业务逻辑与缓存写入。"""
        if not cache:
            return
            
        logger.info(f"[{PLUGIN_NAME}] 开始定时任务...")
        try:
            # TODO: 执行耗时操作 (如爬虫、大数据分析)
            data = {"hot_topic": "AI Development", "updated_at": "now"}
            
            # 写入缓存 (SmartCache 接口)
            await cache.set(CACHE_KEY_PREFIX, data, ttl=3600*6)
            
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 定时任务失败: {e}", exc_info=True)

    async def get_output_scheduled(_name: str, context: dict) -> dict[str, Any]:
        """定时模式的输出函数：仅负责读取缓存，快速返回"""
        if not cache:
            return {}
            
        data = await cache.get(CACHE_KEY_PREFIX)
        if not data:
            return {}
            
        return {
            "analysis": {
                **context.get("analysis", {}),
                PLUGIN_NAME: data
            }
        }

    # -----------------------------------------------------------------------
    # 3. 注册插件 (请根据需要选择一种模式取消注释)
    # -----------------------------------------------------------------------
    
    # === 选项 1: 注册为实时插件 ===
    plugin_center.register_plugin(
        PLUGIN_NAME,
        PLUGIN_TYPE_REALTIME,
        get_output=get_output_realtime
    )

    # === 选项 2: 注册为定时插件 ===
    # plugin_center.register_plugin(
    #     PLUGIN_NAME,
    #     PLUGIN_TYPE_SCHEDULED,
    #     get_output=get_output_scheduled,
    #     refresh_func=refresh,
    #     schedule_config={"interval_hours": 6} # 每 6 小时执行一次 refresh
    # )


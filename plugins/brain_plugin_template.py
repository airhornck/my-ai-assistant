"""
脑级插件开发模板 (Brain Plugin Template)
=========================================

此文件提供了一个标准的脑级插件开发模板。
脑级插件 (Brain Plugin) 是依附于特定“脑”（如分析脑 Analysis Brain、生成脑 Generation Brain）的能力模块。

主要特点：
1. **依赖注入**：通过 `register` 函数的 `config` 参数获取系统服务（AI Service, Cache, Memory 等）。
2. **生命周期**：
   - `realtime` (实时): 每次调用时实时执行。
   - `scheduled` (定时): 后台定时刷新缓存，调用时仅读取数据。
3. **统一接口**：通过 `get_output(name, context)` 返回结果，结果通常是一个字典，会合并到 Context 中。

开发步骤：
1. 复制此文件到 `plugins/你的插件名/plugin.py` 或 `plugins/你的插件名.py`。
2. 修改 `register` 函数中的业务逻辑。
3. 在 `core/brain_plugin_center.py` 的 `ANALYSIS_BRAIN_PLUGINS` (或其他脑列表) 中添加注册项：
   `("plugins.你的插件名", "register"),`

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
    插件注册入口函数。
    
    Args:
        plugin_center: 插件管理中心实例，用于调用 register_plugin
        config: 全局配置字典，包含:
            - "ai_service": AI 服务实例 (SimpleAIService)
            - "cache": 缓存实例 (SmartCache)
            - "memory_service": 记忆服务 (MemoryService)
            - ...其他全局配置
    """
    # 1. 获取依赖服务
    ai_service = config.get("ai_service")
    cache = config.get("cache")
    memory_service = config.get("memory_service")

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
    # 适用于：爬虫、热点监控、定期报表等不需要实时响应用户输入的场景。
    # -----------------------------------------------------------------------
    async def refresh() -> None:
        """定时任务回调：负责更新缓存"""
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


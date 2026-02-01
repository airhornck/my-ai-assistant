"""
插件工作流模板：定义 build_workflow(config) 与节点，返回 LangGraph CompiledGraph。

【如何访问共享服务】
- config 由 main.py lifespan 中 init_plugins(config) 传入，通常包含：
  - config["ai_service"]: SimpleAIService 实例（带缓存、用于 analyze/generate 等）
  - config.get("memory_service"): 可选，MemoryService 实例；若未传入，可在插件内自行
    MemoryService() 创建（与 basic_workflow 一致）。
- 在 build_workflow(config) 内取出服务并闭包到节点中，例如：
  ai_svc = config.get("ai_service") or SimpleAIService()
  memory_svc = config.get("memory_service") or MemoryService()

【如何遵守 MetaState / State 数据格式约定】
- 元工作流编排时传入的 state 是 basic_workflow 的 State 子集，且编排节点会合并子工作流
  返回的 state。因此插件工作流的「输入 state」和「输出 state」必须与 State 兼容：
  - 必选字段：user_input (str), analysis (str), content (str), session_id (str), user_id (str),
    evaluation (dict), need_revision (bool), stage_durations (dict), analyze_cache_hit (bool),
    used_tags (list)。
- 节点返回值应使用「增量更新」：return { **state, "content": new_content, ... }，
  不要缺失上述字段，否则上游合并时可能丢失。
- 若插件被 meta_workflow 的 orchestration_node 按 step_name 调用，无需处理 plan /
  current_step / thinking_logs / step_outputs（由元工作流维护）；只需读写 State 约定字段。
- 详见 workflows/types.py 的 MetaState 与 workflows/basic_workflow.py 的 State。
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

# 按需从项目根导入（插件若在项目内，可直接 import）
# from services.ai_service import SimpleAIService
# from services.memory_service import MemoryService
# from workflows.basic_workflow import State  # 用于类型提示或 TypedDict 兼容

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 状态类型：与 basic_workflow.State 保持一致，确保与 MetaState 兼容
# 编排传入的 sub_state 包含以下字段，节点返回的 state 也应包含这些键
# ---------------------------------------------------------------------------
# user_input: str
# analysis: str
# content: str
# session_id: str
# user_id: str
# evaluation: dict
# need_revision: bool
# stage_durations: dict   # 各阶段耗时（秒）
# analyze_cache_hit: bool
# used_tags: list


def build_workflow(config: dict[str, Any] | None = None) -> Any:
    """
    插件入口：根据 config 构建并返回 LangGraph CompiledGraph。

    - config 通常包含 ai_service、可选 memory_service，由 init_plugins(config) 传入。
    - 返回的图必须支持 .ainvoke(state)，且 state 入参/出参符合 State 约定。
    """
    config = config or {}

    # ---------- 从 config 获取共享服务（详见本文件顶部注释）----------
    # ai_svc = config.get("ai_service")
    # if ai_svc is None:
    #     from services.ai_service import SimpleAIService
    #     ai_svc = SimpleAIService()
    # memory_svc = config.get("memory_service")
    # if memory_svc is None:
    #     from services.memory_service import MemoryService
    #     memory_svc = MemoryService()

    async def _placeholder_node(state: dict) -> dict:
        """
        占位节点：直接透传 state，并确保返回包含 State 约定字段。
        实际插件中应在此调用 ai_svc / memory_svc，并返回增量更新的 state。
        """
        # 示例：保持 State 约定，只更新 content（其他字段用 state 原有值）
        return {
            **state,
            "content": state.get("content", "") or "[插件占位输出]",
            "analysis": state.get("analysis", ""),
            "evaluation": state.get("evaluation", {}),
            "need_revision": state.get("need_revision", False),
            "stage_durations": state.get("stage_durations", {}),
            "analyze_cache_hit": state.get("analyze_cache_hit", False),
            "used_tags": state.get("used_tags", []),
        }

    # 使用 StateGraph 时，状态类型可用 dict 或与 State 兼容的 TypedDict
    workflow = StateGraph(dict)
    workflow.add_node("placeholder", _placeholder_node)
    workflow.set_entry_point("placeholder")
    workflow.add_edge("placeholder", END)
    return workflow.compile()

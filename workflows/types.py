"""
工作流状态类型定义。
MetaState 继承并扩展 basic_workflow 的 State，用于元工作流（规划 → 编排 → 汇总）。
"""
from __future__ import annotations

from typing import TypedDict

from workflows.basic_workflow import State


class ThinkingLogEntry(TypedDict):
    """单条思考日志。"""
    step: str
    thought: str
    timestamp: str


class MetaState(State):
    """
    元工作流状态：在 State 基础上增加规划、当前步骤、思考日志与分步输出。
    所有节点返回的 state 均需符合此结构。
    """
    plan: list  # 规划步骤列表，如 ["分析竞品", "关联热点", "生成创意"]
    current_step: int  # 当前执行到的步骤索引
    thinking_logs: list  # 每项为 {"step": str, "thought": str, "timestamp": str}
    step_outputs: list  # 各步子工作流输出，供 compilation 汇总

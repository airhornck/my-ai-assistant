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
    编排层子图/节点会读写 search_context、memory_context、kb_context、effective_tags 等。
    """
    plan: list  # 规划步骤列表（供前端思考过程展示）
    task_type: str  # 任务类型：campaign_or_copy | ip_diagnosis | ip_building_plan，供编排分支
    current_step: int  # 当前执行到的步骤索引
    thinking_logs: list  # 每项为 {"step": str, "thought": str, "timestamp": str}
    step_outputs: list  # 各步子工作流输出，供 compilation 汇总
    analysis_plugins: list  # 本轮要执行的分析脑插件名列表（由 plan 推导，供编排执行）
    generation_plugins: list  # 本轮要执行的生成脑插件名列表（由 plan 推导，供编排执行）
    search_context: str  # 编排层：网络检索等结果
    memory_context: str  # 编排层：用户记忆/偏好
    kb_context: str  # 编排层：知识库检索结果
    effective_tags: list  # 编排层：本轮生效的标签（与 used_tags 对齐，compilation 前可写 used_tags）

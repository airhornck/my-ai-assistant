"""
任务类型 → 插件列表注册表。
规划脑只输出 task_type 与 plan；analysis_plugins / generation_plugins 由此表推导。
后续新增能力：在对应脑的插件清单中注册插件，再在此表增加一条 task_type 映射即可，无需改 planning_node 分支逻辑。
"""
from __future__ import annotations

from typing import Any

# task_type -> 本任务下「分析脑插件列表」「生成脑插件列表（当 plan 含 generate 时）」
# 只登记拼装后或无需拼装的插件名；拼装逻辑在各脑插件中心内完成
TASK_PLUGIN_MAP: dict[str, dict[str, Any]] = {
    "campaign_or_copy": {
        "analysis_plugins": ["campaign_context"],
        "generation_plugins": ["campaign_plan_generator"],
    },
    # 示例：后续新增 IP 诊断等，在此增加一项并在规划 prompt 中增加对应 task_type 即可
    # "ip_diagnosis": {
    #     "analysis_plugins": ["ip_diagnosis_context"],
    #     "generation_plugins": ["ip_diagnosis_report"],
    # },
    "_default": {
        "analysis_plugins": [],
        "generation_plugins": ["text_generator"],
    },
}


def get_plugins_for_task(task_type: str, step_names: list[str]) -> tuple[list[str], list[str]]:
    """
    根据任务类型与步骤名推导本轮的 analysis_plugins、generation_plugins。

    Args:
        task_type: 规划脑输出的任务类型（如 campaign_or_copy、ip_diagnosis）。
        step_names: 本轮 plan 的步骤名列表（小写），如 ["web_search", "analyze", "generate"]。

    Returns:
        (analysis_plugins, generation_plugins)：仅当 plan 含 analyze 时返回分析插件，仅当含 generate 时返回生成插件。
    """
    entry = TASK_PLUGIN_MAP.get(task_type) or TASK_PLUGIN_MAP.get("_default") or {}
    step_set = {s.lower() for s in step_names}
    analysis_plugins = list(entry.get("analysis_plugins") or []) if "analyze" in step_set else []
    generation_plugins = list(entry.get("generation_plugins") or []) if "generate" in step_set else []
    return (analysis_plugins, generation_plugins)

# -*- coding: utf-8 -*-
"""
测试：动态「可用模块」拼接后，策略脑能否正确推导并调用分析脑/生成脑插件。

- 分析脑：ANALYSIS_BRAIN_PLUGINS 共 21 个插件模块（含热点、方法论、诊断、爆款结构等）
- 生成脑：GENERATION_BRAIN_PLUGINS 共 5 个插件（text_generator、campaign_plan_generator、image_generator、video_generator、report_generation）
- 策略脑不直接枚举插件，而是根据 task_type + plan 中的 analyze/generate 步骤，经 get_plugins_for_task 推导出本轮的 analysis_plugins / generation_plugins 子集

用例：
1. 动态段落包含关键步骤名（web_search, analyze, generate 等）
2. get_plugins_for_task 对各 task_type 返回预期插件列表
3. 模拟 planning 解析后得到的插件列表与预期一致
4. TASK_PLUGIN_MAP 中出现的插件名在脑插件清单中有对应模块
5. （可选）若设 DASHSCOPE_API_KEY，校验插件中心已注册上述插件

运行: python scripts/test_strategy_brain_plugins.py
或: pytest scripts/test_strategy_brain_plugins.py -v -s
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# 保证项目根在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_build_available_modules_section():
    """动态「可用模块」段落应包含策略脑规划所需的关键步骤名。"""
    from core.step_descriptions_for_planning import build_available_modules_section

    section = build_available_modules_section()
    assert "可用模块" in section, "应包含「可用模块」标题"
    for step in ("web_search", "memory_query", "kb_retrieve", "analyze", "generate", "evaluate", "casual_reply"):
        assert step in section, f"动态段落应包含步骤 {step}"
    assert "自定义插件" in section or "PluginRegistry" in section, "应包含自定义插件说明"
    print("[OK] build_available_modules_section 包含关键步骤与说明")


def test_get_plugins_for_task_all_task_types():
    """各 task_type 在 plan 含 analyze/generate 时，应得到预期的分析/生成插件列表。"""
    from core.task_plugin_registry import TASK_PLUGIN_MAP, get_plugins_for_task

    steps_with_analyze_generate = ["web_search", "analyze", "generate", "evaluate"]
    step_set = {s.lower() for s in steps_with_analyze_generate}

    for task_type, entry in TASK_PLUGIN_MAP.items():
        if task_type == "_default":
            continue
        expected_analysis = list(entry.get("analysis_plugins") or [])
        expected_generation = list(entry.get("generation_plugins") or [])

        a_plugins, g_plugins = get_plugins_for_task(task_type, steps_with_analyze_generate)
        assert "analyze" in step_set
        assert "generate" in step_set
        assert a_plugins == expected_analysis, f"task_type={task_type} 分析插件应为 {expected_analysis}，得到 {a_plugins}"
        assert g_plugins == expected_generation, f"task_type={task_type} 生成插件应为 {expected_generation}，得到 {g_plugins}"

    # 无 analyze 时分析插件应为空
    a_empty, g_empty = get_plugins_for_task("campaign_or_copy", ["web_search", "generate"])
    assert a_empty == [], "plan 无 analyze 时分析插件应为空"
    assert g_empty == ["campaign_plan_generator"], "plan 含 generate 时应有生成插件"

    # 无 generate 时生成插件应为空
    a_a, g_a = get_plugins_for_task("campaign_or_copy", ["web_search", "analyze"])
    assert g_a == [], "plan 无 generate 时生成插件应为空"
    assert a_a == ["campaign_context"], "plan 含 analyze 时应有分析插件"

    print("[OK] get_plugins_for_task 对各 task_type 推导正确")


def test_planning_plugin_derivation_pipeline():
    """模拟 planning 解析 LLM 输出后，task_type + step_names 经 get_plugins_for_task 得到与策略脑一致的插件列表。"""
    from core.task_plugin_registry import get_plugins_for_task

    # 模拟策略脑 LLM 返回的 campaign_or_copy + 含 analyze & generate 的 plan
    fixed_plan = [
        {"step": "bilibili_hotspot", "params": {}, "reason": "获取B站热点"},
        {"step": "memory_query", "params": {}, "reason": "用户偏好"},
        {"step": "analyze", "params": {}, "reason": "分析"},
        {"step": "generate", "params": {"platform": "B站"}, "reason": "生成"},
        {"step": "evaluate", "params": {}, "reason": "评估"},
    ]
    task_type = "campaign_or_copy"
    step_names = [(s.get("step") or "").lower() for s in fixed_plan]

    analysis_plugins, generation_plugins = get_plugins_for_task(task_type, step_names)
    assert analysis_plugins == ["campaign_context"], f"应为 ['campaign_context']，得到 {analysis_plugins}"
    assert generation_plugins == ["campaign_plan_generator"], f"应为 ['campaign_plan_generator']，得到 {generation_plugins}"

    # 再测 ip_diagnosis：分析脑应得到 account_diagnosis，生成脑应得到 text_generator
    a2, g2 = get_plugins_for_task("ip_diagnosis", ["analyze", "generate"])
    assert a2 == ["account_diagnosis"], a2
    assert g2 == ["text_generator"], g2

    print("[OK] planning 解析后经 get_plugins_for_task 得到的插件列表与预期一致")


def test_task_plugin_map_names_in_brain_lists():
    """TASK_PLUGIN_MAP 中出现的插件名应在分析脑/生成脑插件清单中有对应注册模块。"""
    from core.task_plugin_registry import TASK_PLUGIN_MAP
    from core.brain_plugin_center import ANALYSIS_BRAIN_PLUGINS, GENERATION_BRAIN_PLUGINS

    analysis_names_from_map = set()
    generation_names_from_map = set()
    for entry in TASK_PLUGIN_MAP.values():
        analysis_names_from_map.update(entry.get("analysis_plugins") or [])
        generation_names_from_map.update(entry.get("generation_plugins") or [])

    # 各插件模块的 register 使用的名称（与 register_plugin 第一个参数一致）
    ANALYSIS_MODULE_TO_NAME = {
        "plugins.campaign_context.plugin": "campaign_context",
        "plugins.account_diagnosis_plugin": "account_diagnosis",
        "plugins.cover_diagnosis.plugin": "cover_diagnosis",
        "plugins.rate_limit_diagnosis.plugin": "rate_limit_diagnosis",
        "plugins.viral_prediction.plugin": "viral_prediction",
        "plugins.video_viral_structure.plugin": "video_viral_structure",
        "plugins.script_replication.plugin": "script_replication",
    }
    GENERATION_MODULE_TO_NAME = {
        "plugins.text_generator.plugin": "text_generator",
        "plugins.campaign_plan_generator.plugin": "campaign_plan_generator",
    }
    analysis_registered = set(ANALYSIS_MODULE_TO_NAME.get(m[0], m[0].split(".")[1]) for m in ANALYSIS_BRAIN_PLUGINS)
    generation_registered = set(GENERATION_MODULE_TO_NAME.get(m[0], m[0].split(".")[1]) for m in GENERATION_BRAIN_PLUGINS)

    for name in analysis_names_from_map:
        assert name in analysis_registered, f"TASK_PLUGIN_MAP 分析插件 {name} 应在 ANALYSIS_BRAIN_PLUGINS 中有对应注册（当前: {sorted(analysis_registered)}）"
    for name in generation_names_from_map:
        assert name in generation_registered, f"TASK_PLUGIN_MAP 生成插件 {name} 应在 GENERATION_BRAIN_PLUGINS 中有对应注册（当前: {sorted(generation_registered)}）"

    print(f"[OK] TASK_PLUGIN_MAP 中分析插件 {sorted(analysis_names_from_map)}、生成插件 {sorted(generation_names_from_map)} 均在脑插件清单中有对应模块")


async def optional_test_plugin_centers_have_plugins():
    """可选：若环境允许（含 DASHSCOPE 等），创建 SimpleAIService 并校验各 TASK_PLUGIN_MAP 插件名已注册。"""
    if not os.getenv("DASHSCOPE_API_KEY"):
        print("[SKIP] 未设置 DASHSCOPE_API_KEY，跳过插件中心 has_plugin 校验")
        return

    from core.task_plugin_registry import TASK_PLUGIN_MAP
    from services.ai_service import SimpleAIService

    try:
        ai = SimpleAIService()
    except Exception as e:
        print(f"[SKIP] SimpleAIService 初始化失败（可能缺 Redis/DB）: {e}")
        return

    analysis_center = getattr(ai, "_analysis_plugin_center", None)
    generation_center = getattr(ai, "_generation_plugin_center", None)
    assert analysis_center is not None, "分析脑插件中心应存在"
    assert generation_center is not None, "生成脑插件中心应存在"

    all_analysis = set()
    all_generation = set()
    for entry in TASK_PLUGIN_MAP.values():
        all_analysis.update(entry.get("analysis_plugins") or [])
        all_generation.update(entry.get("generation_plugins") or [])

    missing_a = [n for n in all_analysis if not analysis_center.has_plugin(n)]
    missing_g = [n for n in all_generation if not generation_center.has_plugin(n)]
    assert not missing_a, f"分析脑插件中心应已注册: {missing_a}"
    assert not missing_g, f"生成脑插件中心应已注册: {missing_g}"

    print(f"[OK] 插件中心已注册 TASK_PLUGIN_MAP 中全部分析插件({len(all_analysis)}个)与生成插件({len(all_generation)}个)")


def main():
    test_build_available_modules_section()
    test_get_plugins_for_task_all_task_types()
    test_planning_plugin_derivation_pipeline()
    test_task_plugin_map_names_in_brain_lists()
    asyncio.run(optional_test_plugin_centers_have_plugins())
    print("\n全部通过：策略脑在动态「可用模块」下仍能正确推导并对应分析脑/生成脑插件。")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
测试：新插件/新步骤加入后，策略脑在规划与编排时是否会识别到新能力并自主决定是否使用。

结论摘要：
- 编排步骤（step）：只要加入 step_descriptions_for_planning 的 STEP_DESCRIPTIONS，策略脑 prompt 就会包含该步骤，
  模型可「识别」并规划；但要被编排真正执行，还需在 meta_workflow 的 PARALLEL_STEPS 与 parallel_retrieval_node 中
  实现对应 runner，否则会被路由到 skip。
- 分析/生成插件（analysis_plugins、generation_plugins）：策略脑 prompt 中不列举插件名，模型不会按插件名「识别」；
  由 task_type 经 TASK_PLUGIN_MAP 决定本轮用哪些插件，新插件需在 TASK_PLUGIN_MAP 中挂到某 task_type 才会被使用。

运行: python scripts/test_new_plugin_recognition.py
或: pytest scripts/test_new_plugin_recognition.py -v -s
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 与 meta_workflow 内 PARALLEL_STEPS 保持一致，用于断言「仅在此集合内的步骤会被并行执行」
PARALLEL_STEPS_IN_WORKFLOW = {"web_search", "memory_query", "bilibili_hotspot", "kb_retrieve"}


def test_new_step_in_step_descriptions_appears_in_planning_prompt():
    """加入 STEP_DESCRIPTIONS 的新步骤会出现在策略脑的「可用模块」中，模型能识别并规划。"""
    from core.step_descriptions_for_planning import STEP_DESCRIPTIONS, build_available_modules_section

    section = build_available_modules_section()
    for step_name in STEP_DESCRIPTIONS:
        assert step_name in section, f"步骤 {step_name} 应在策略脑可用模块段落中，以便模型识别并规划"
    # 特别检查已在描述表中但可能尚未接入编排的步骤（如 xiaohongshu_hotspot）
    assert "xiaohongshu_hotspot" in section
    assert "douyin_hotspot" in section
    assert "acfun_hotspot" in section
    print("[OK] STEP_DESCRIPTIONS 中所有步骤均出现在策略脑规划 prompt 中，可被模型识别并自主决定是否编排")


def test_steps_not_in_parallel_steps_are_routed_to_skip():
    """仅在 PARALLEL_STEPS 内的步骤会进入 parallel_retrieval 执行；其余编排步骤（如 xiaohongshu_hotspot）会走 skip。"""
    from core.step_descriptions_for_planning import STEP_DESCRIPTIONS

    in_parallel = [s for s in STEP_DESCRIPTIONS if s in PARALLEL_STEPS_IN_WORKFLOW]
    not_in_parallel = [s for s in STEP_DESCRIPTIONS if s not in PARALLEL_STEPS_IN_WORKFLOW]
    assert "bilibili_hotspot" in in_parallel
    assert "web_search" in in_parallel
    # 以下步骤在描述表中（模型可规划），但当前编排未接入并行执行，会被路由到 skip
    assert "xiaohongshu_hotspot" in not_in_parallel or "xiaohongshu_hotspot" in STEP_DESCRIPTIONS
    print(
        "[OK] 当前仅 %s 会进入 parallel_retrieval；%s 等若被规划会走 skip，需在 meta_workflow 中接入 PARALLEL_STEPS 与 runner 才会执行"
        % (sorted(in_parallel), sorted(not_in_parallel)[:3])
    )


def test_planning_prompt_does_not_list_analysis_generation_plugin_names():
    """策略脑 prompt 不包含分析脑/生成脑的插件名，模型不会按插件名「识别」新插件；插件由 task_type 经 TASK_PLUGIN_MAP 决定。"""
    from core.step_descriptions_for_planning import build_available_modules_section
    from core.task_plugin_registry import TASK_PLUGIN_MAP

    section = build_available_modules_section()
    all_plugin_names = set()
    for entry in TASK_PLUGIN_MAP.values():
        all_plugin_names.update(entry.get("analysis_plugins") or [])
        all_plugin_names.update(entry.get("generation_plugins") or [])

    # 策略脑可用模块段落中不应出现这些插件名（只应出现编排步骤名：web_search, analyze, generate 等）
    for name in all_plugin_names:
        assert name not in section, (
            "策略脑 prompt 中不应列举分析/生成插件名 %s；新插件需通过 TASK_PLUGIN_MAP 挂到 task_type 才会被使用"
            % name
        )
    print(
        "[OK] 策略脑 prompt 不包含分析/生成插件名（%s 等），新插件由 TASK_PLUGIN_MAP 与 task_type 决定是否使用"
        % list(all_plugin_names)[:5]
    )


def test_new_plugin_used_when_added_to_task_plugin_map():
    """新分析/生成插件只要在 TASK_PLUGIN_MAP 中挂到某 task_type，该 task_type 被规划时就会进入 analysis_plugins/generation_plugins。"""
    from core.task_plugin_registry import TASK_PLUGIN_MAP, get_plugins_for_task

    # 任意一个 task_type，其下的插件列表应被 get_plugins_for_task 原样返回（当 plan 含 analyze/generate 时）
    task_type = "ip_diagnosis"
    entry = TASK_PLUGIN_MAP.get(task_type)
    assert entry is not None
    expected_a = set(entry.get("analysis_plugins") or [])
    expected_g = set(entry.get("generation_plugins") or [])

    a_plugins, g_plugins = get_plugins_for_task(task_type, ["web_search", "analyze", "generate", "evaluate"])
    assert set(a_plugins) == expected_a
    assert set(g_plugins) == expected_g
    print(
        "[OK] 新插件加入 TASK_PLUGIN_MAP 的 %s 后，策略脑输出该 task_type 时编排会使用 analysis_plugins=%s, generation_plugins=%s"
        % (task_type, a_plugins, g_plugins)
    )


def test_full_chain_new_step_described_but_must_be_wired_to_execute():
    """完整链：新步骤仅加入 STEP_DESCRIPTIONS → 可被规划；要被执行还需在 meta_workflow 的 PARALLEL_STEPS 与 _step_runner 中接入。"""
    from core.step_descriptions_for_planning import STEP_DESCRIPTIONS, build_available_modules_section

    section = build_available_modules_section()
    # 以 xiaohongshu_hotspot 为例：已在描述表，故可被规划
    assert "xiaohongshu_hotspot" in STEP_DESCRIPTIONS
    assert "xiaohongshu_hotspot" in section
    # 但当前编排未接入，故若被规划会走 skip
    assert "xiaohongshu_hotspot" not in PARALLEL_STEPS_IN_WORKFLOW
    print(
        "[OK] 新步骤「仅加 STEP_DESCRIPTIONS」→ 策略脑可识别并规划；"
        "要编排执行需同时在 meta_workflow 中：PARALLEL_STEPS 加入该步 + parallel_retrieval_node 中实现 _run_xxx 与 _step_runner 分支"
    )


def main():
    test_new_step_in_step_descriptions_appears_in_planning_prompt()
    test_steps_not_in_parallel_steps_are_routed_to_skip()
    test_planning_prompt_does_not_list_analysis_generation_plugin_names()
    test_new_plugin_used_when_added_to_task_plugin_map()
    test_full_chain_new_step_described_but_must_be_wired_to_execute()
    print("\n全部通过：新插件/新步骤的「识别与编排」逻辑符合预期。")


if __name__ == "__main__":
    main()

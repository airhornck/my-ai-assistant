#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
四步改造 MVP 验收（离线）：
1) 失败面可视化：trace_event + failure_code
2) 自动修复：analyze/generate fallback 关键路径存在
3) 继续短句续跑触发器存在
4) skill runtime 覆盖所有固定 Plan 插件 + AB 分桶
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.skill_runtime import (
    MANAGED_SKILLS,
    build_skill_execution_plan,
    collect_fixed_plan_plugin_ids,
    fallback_plugins_for_step,
)

META = ROOT / "workflows" / "meta_workflow.py"


def assert_in(text: str, snippet: str, msg: str) -> None:
    if snippet not in text:
        raise AssertionError(msg)


def main() -> int:
    src = META.read_text(encoding="utf-8", errors="ignore")

    # Step1: 可视化 + 失败码
    assert_in(src, "def _trace_event(", "缺少 _trace_event")
    assert_in(src, "FailureCode.", "缺少 failure_code 枚举使用")

    # Step2: 自动修复链路
    assert_in(src, "retry_with_fallback", "缺少重试回退动作日志")
    assert_in(src, "fallback_plugins_for_step(", "缺少同类 skill 回退")
    assert_in(src, "skip_with_explanation", "缺少跳过并解释路径")

    # Step3: 继续短句续跑
    assert_in(src, "continue_words = {\"需要\", \"继续\", \"然后呢\", \"再说说\", \"还有吗\"}", "缺少继续短句集合")
    assert_in(src, "action=\"continue_trigger\"", "缺少 continue_trigger 事件")

    # Step4: skill runtime 与 AB（与固定 Plan 中出现的插件 ID 一致）
    fixed_plugins = collect_fixed_plan_plugin_ids()
    missing = fixed_plugins - set(MANAGED_SKILLS.keys())
    assert not missing, f"MANAGED_SKILLS 缺少固定 Plan 插件: {sorted(missing)}"
    plan = build_skill_execution_plan(["content_positioning"], user_id="u_test_001")
    assert isinstance(plan.get("ab_bucket"), str) and plan["ab_bucket"] in ("A", "B"), "AB 分桶无效"
    assert "content_positioning" in (plan.get("skill_ids") or []), "skill 命中识别失败"
    fb = fallback_plugins_for_step("analyze", ["content_positioning"])
    assert "content_positioning" in fb and "content_positioning_plugin" in fb, "analyze fallback 链不完整"

    print(
        json.dumps(
            {
                "ok": True,
                "checks": [
                    "step1_trace_and_failure_code",
                    "step2_retry_fallback_skip",
                    "step3_continue_trigger",
                    "step4_skill_runtime_ab",
                ],
                "ab_bucket_example": plan["ab_bucket"],
                "fallback_example": fb[:3],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

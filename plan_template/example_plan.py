"""
Plan 模板开发示例：复制本文件到 plans/templates/ 下并修改 template_id、steps、选择器等，
然后按「两步添加」在 plans/templates/__init__.py 中 import 本模块以完成注册。

两步添加（类似插件）：
  1. 复制本文件为 plans/templates/<name>.py，实现 register_plan() 并在文件末尾调用。
  2. 在 plans/templates/__init__.py 中增加：import plans.templates.<name>  # noqa: F401

本示例展示：
- 固定 Plan 的 name（展示名）、description（流程说明）、steps 结构
- 可选的 intent_selector 与 selector_priority
- 通过 plans.registry.register 注册
"""
from __future__ import annotations


def _intent_selector(intent: str, ip_context: dict) -> bool:
    """示例：当意图或话题命中时使用本模板。"""
    topic = (ip_context.get("topic") or "").lower()
    if "示例" in intent or "example" in intent:
        return True
    if "示例话题" in topic:
        return True
    return False


# 模板 ID 常量（若需对外使用，在 plans/templates/__init__.py 中 re-export）
TEMPLATE_EXAMPLE_MY_PLAN = "example_my_plan"


def register_plan() -> None:
    """注册本 Plan 模板。模块被 import 时在文件末尾调用一次。"""
    from plans.registry import PLAN_TYPE_FIXED, register

    register(
        TEMPLATE_EXAMPLE_MY_PLAN,
        name="示例我的计划",
        plan_type=PLAN_TYPE_FIXED,
        steps=[
            {"step": "memory_query", "plugins": [], "params": {}, "reason": "查询用户偏好"},
            {"step": "analyze", "plugins": ["topic_selection_plugin"], "params": {}, "reason": "选题分析"},
            {"step": "generate", "plugins": ["text_generator"], "params": {"platform": ""}, "reason": "生成内容"},
        ],
        description="示例 Plan：偏好 → 选题 → 生成",
        intent_selector=_intent_selector,
        selector_priority=50,
    )


# 复制到 plans/templates/<name>.py 后取消下一行注释，并在 __init__.py 中 import 本模块
# register_plan()

"""
Plan 模板包：每个固定 Plan 一个文件，加载时自动注册。

新增固定 Plan 两步添加（类似插件）：
  1. 在 plans/templates/ 下新建 <name>.py，定义 TEMPLATE_ID/常量、steps、可选 intent_selector，并调用 register_plan()。
  2. 在本文件中添加一行：import plans.templates.<name>  # noqa: F401
"""
from __future__ import annotations

# 导入即注册（各模块末尾调用 register_plan()）
import plans.templates.account_building  # noqa: F401
import plans.templates.capability_case_library  # noqa: F401
import plans.templates.capability_content_direction_ranking  # noqa: F401
import plans.templates.capability_content_positioning_matrix  # noqa: F401
import plans.templates.capability_weekly_decision_snapshot  # noqa: F401
import plans.templates.content_matrix  # noqa: F401
import plans.templates.ip_diagnosis  # noqa: F401

# 统一导出模板 ID 常量，供 plans/__init__.py 与业务方使用
from plans.templates.account_building import TEMPLATE_ACCOUNT_BUILDING
from plans.templates.capability_case_library import CAPABILITY_TEMPLATE_CASE_LIBRARY
from plans.templates.capability_content_direction_ranking import (
    CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING,
)
from plans.templates.capability_content_positioning_matrix import (
    CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX,
)
from plans.templates.capability_weekly_decision_snapshot import (
    CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT,
)
from plans.templates.content_matrix import TEMPLATE_CONTENT_MATRIX
from plans.templates.ip_diagnosis import TEMPLATE_IP_DIAGNOSIS

__all__ = [
    "CAPABILITY_TEMPLATE_CASE_LIBRARY",
    "CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING",
    "CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX",
    "CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT",
    "TEMPLATE_ACCOUNT_BUILDING",
    "TEMPLATE_CONTENT_MATRIX",
    "TEMPLATE_IP_DIAGNOSIS",
]

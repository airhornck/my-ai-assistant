"""
平台规则工厂。
"""
from __future__ import annotations

import os

from modules.platform_rules.port import PlatformRulesPort
from modules.platform_rules.adapter import YamlPlatformRulesAdapter


def get_platform_rules(
    *,
    rules_dir: str | None = None,
) -> PlatformRulesPort:
    """
    获取平台规则 Port。
    环境变量：PLATFORM_RULES_DIR 指定规则目录。
    默认加载 config/platform_rules/ 且兼容 config/diagnosis_thresholds.yaml。
    """
    dir_path = rules_dir or os.getenv("PLATFORM_RULES_DIR", "config/platform_rules")
    return YamlPlatformRulesAdapter(rules_dir=dir_path)

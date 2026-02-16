"""
平台规则适配器：组合 YAML 加载 + 兼容 diagnosis_thresholds。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from modules.platform_rules.port import PlatformRulesPort, RuleSet
from modules.platform_rules.yaml_loader import load_rules_from_dir, load_legacy_diagnosis_thresholds

logger = logging.getLogger(__name__)


class YamlPlatformRulesAdapter(PlatformRulesPort):
    """基于 YAML 的平台规则实现。"""

    def __init__(
        self,
        rules_dir: str | None = None,
        legacy_thresholds_path: str = "config/diagnosis_thresholds.yaml",
    ) -> None:
        self._rules_dir = rules_dir
        self._legacy_path = legacy_thresholds_path
        self._rules: dict[str, RuleSet] = {}
        self._legacy: dict[str, dict[str, float]] = {}
        self._load()

    def _load(self) -> None:
        self._rules = load_rules_from_dir(self._rules_dir)
        self._legacy = load_legacy_diagnosis_thresholds(self._legacy_path)
        # 将 legacy 的阈值合并到各平台
        for platform, thresh in self._legacy.items():
            if platform not in self._rules:
                self._rules[platform] = RuleSet(platform=platform)
            self._rules[platform].thresholds.update(thresh)

    def reload(self) -> None:
        self._load()
        logger.info("平台规则已重新加载")

    def get_rules(self, platform: str) -> RuleSet:
        return self._rules.get(platform, RuleSet(platform=platform))

    def get_sensitive_words(self, platform: str) -> list[str]:
        return self.get_rules(platform).sensitive_words.copy()

    def get_prohibited_visuals(self, platform: str) -> list[str]:
        return self.get_rules(platform).prohibited_visuals.copy()

    def get_thresholds(self, platform: str) -> dict[str, float]:
        return self.get_rules(platform).thresholds.copy()

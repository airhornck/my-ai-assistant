"""
平台规则 Port：敏感词、违禁画面、阈值等。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RuleSet:
    """单平台规则集。"""

    platform: str
    sensitive_words: list[str] = field(default_factory=list)  # 文本敏感词
    sensitive_patterns: list[str] = field(default_factory=list)  # 正则
    prohibited_visuals: list[str] = field(default_factory=list)  # 违禁画面描述
    marketing_patterns: list[dict[str, Any]] = field(default_factory=list)  # 营销行为模式
    thresholds: dict[str, float] = field(default_factory=dict)  # 继承 diagnosis_thresholds
    extra: dict[str, Any] = field(default_factory=dict)


class PlatformRulesPort(ABC):
    """平台规则端口。"""

    @abstractmethod
    def get_rules(self, platform: str) -> RuleSet:
        """获取指定平台规则集。"""
        ...

    @abstractmethod
    def get_sensitive_words(self, platform: str) -> list[str]:
        """获取敏感词列表。"""
        ...

    @abstractmethod
    def get_prohibited_visuals(self, platform: str) -> list[str]:
        """获取违禁画面描述。"""
        ...

    @abstractmethod
    def get_thresholds(self, platform: str) -> dict[str, float]:
        """获取阈值配置。"""
        ...

    def reload(self) -> None:
        """热更新规则（可选实现）。"""
        pass

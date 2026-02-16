"""
平台规则知识库：敏感词、违禁画面、限流规则等。
按需调用，不进入主流程。供限流诊断、合规检查等插件使用。
"""
from modules.platform_rules.port import PlatformRulesPort, RuleSet
from modules.platform_rules.factory import get_platform_rules

__all__ = [
    "PlatformRulesPort",
    "RuleSet",
    "get_platform_rules",
]

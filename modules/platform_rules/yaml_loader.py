"""
平台规则 YAML 加载器：支持多文件、多平台。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from modules.platform_rules.port import RuleSet

logger = logging.getLogger(__name__)

# 默认规则目录
DEFAULT_RULES_DIR = "config/platform_rules"


def load_rules_from_dir(rules_dir: str | None = None) -> dict[str, RuleSet]:
    """
    从目录加载规则。目录下可有多文件，按 platform 合并。
    文件名如：bilibili.yaml, douyin.yaml, sensitive_words_common.yaml
    """
    rules_dir = rules_dir or DEFAULT_RULES_DIR
    path = Path(rules_dir)
    if not path.exists():
        logger.debug("平台规则目录不存在: %s，使用空规则", rules_dir)
        return _default_rules()

    result: dict[str, RuleSet] = {}
    for f in path.glob("*.yaml"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = yaml.safe_load(fp)
            if not isinstance(data, dict):
                continue
            # 支持单文件多平台：{ bilibili: {...}, douyin: {...} }
            for platform, cfg in data.items():
                if not isinstance(cfg, dict):
                    continue
                rs = result.get(platform, RuleSet(platform=platform))
                rs.sensitive_words.extend(cfg.get("sensitive_words", []) or [])
                rs.sensitive_patterns.extend(cfg.get("sensitive_patterns", []) or [])
                rs.prohibited_visuals.extend(cfg.get("prohibited_visuals", []) or [])
                rs.marketing_patterns.extend(cfg.get("marketing_patterns", []) or [])
                if cfg.get("thresholds"):
                    rs.thresholds.update(cfg["thresholds"])
                result[platform] = rs
        except Exception as e:
            logger.warning("加载规则文件 %s 失败: %s", f, e)
    return result if result else _default_rules()


def load_legacy_diagnosis_thresholds(config_path: str = "config/diagnosis_thresholds.yaml") -> dict[str, dict[str, float]]:
    """加载原有 diagnosis_thresholds，兼容旧配置。"""
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("加载 diagnosis_thresholds 失败: %s", e)
        return {}


def _default_rules() -> dict[str, RuleSet]:
    """默认空规则。"""
    return {
        "default": RuleSet(platform="default"),
    }

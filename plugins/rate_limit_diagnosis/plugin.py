"""
限流诊断插件：分析脑实时插件。
参考 Veogo AI：限流风险秒级扫描。
敏感词、违禁画面、营销行为模式检测。
依赖：platform_rules、multimodal_port（按需，用于画面违规检测）。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

FALLBACK = """【限流诊断】
风险等级：低
（platform_rules 未配置时使用兜底）"""


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """注册限流诊断插件。"""
    platform_rules = config.get("platform_rules")
    multimodal_port = config.get("multimodal_port")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        existing = context.get("analysis") or {}
        if not isinstance(existing, dict):
            existing = {}
        pi = context.get("plugin_input") or {}
        platform = pi.get("platform", "") or "default"
        text = pi.get("script", "") or pi.get("title", "") or ""
        cover_url = pi.get("cover_url", "")

        if not platform_rules:
            return {"analysis": {**existing, "rate_limit_diagnosis": FALLBACK}}

        issues = []
        rules = platform_rules.get_rules(platform)

        # 文本敏感词
        for w in (rules.sensitive_words or [])[:50]:
            if w and w in text:
                issues.append(f"敏感词：{w}")
        for pat in (rules.sensitive_patterns or [])[:20]:
            if pat and re.search(pat, text):
                issues.append(f"敏感模式命中：{pat[:30]}...")

        # 违禁画面（需多模态分析）
        if cover_url and multimodal_port:
            try:
                img_result = await multimodal_port.analyze_image(cover_url, options={"check_violation": True})
                if img_result.violation_detected and img_result.violation_tags:
                    issues.append(f"违禁画面：{', '.join(img_result.violation_tags)}")
            except Exception as e:
                logger.debug("限流诊断：封面分析失败 %s", e)

        # 营销行为模式
        for mp in (rules.marketing_patterns or [])[:10]:
            ptype = mp.get("type", "")
            pattern = mp.get("pattern", "")
            if pattern and pattern in text:
                issues.append(f"营销行为：{ptype}")

        risk = "高" if len(issues) >= 3 else ("中" if issues else "低")
        report = f"""【限流诊断】
风险等级：{risk}
问题项：{chr(10).join(issues) if issues else '未发现明显风险'}
平台：{platform}"""
        return {"analysis": {**existing, "rate_limit_diagnosis": report}}

    plugin_center.register_plugin(
        "rate_limit_diagnosis",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

"""
CTR 预测插件：分析脑实时插件。
封面+标题 → 点击率预估、因子贡献。
依赖：prediction_port、multimodal_port（按需，用于封面特征提取）。
"""
from __future__ import annotations

import logging
from typing import Any

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

FALLBACK = """【CTR 预估】
预估点击率：3%
（prediction_port 未配置时使用兜底）"""


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """注册 CTR 预测插件。"""
    prediction_port = config.get("prediction_port")
    multimodal_port = config.get("multimodal_port")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        existing = context.get("analysis") or {}
        if not isinstance(existing, dict):
            existing = {}
        pi = context.get("plugin_input") or {}
        cover_url = pi.get("cover_url", "")
        title = pi.get("title", "") or pi.get("script", "")[:100]
        platform = pi.get("platform", "") or "default"

        if not prediction_port:
            return {"analysis": {**existing, "ctr_prediction": FALLBACK}}

        cover_features = {}
        if cover_url and multimodal_port:
            try:
                img_result = await multimodal_port.analyze_image(cover_url)
                cover_features = img_result.to_dict()
            except Exception as e:
                logger.debug("CTR 预测：封面分析失败 %s，使用空特征", e)

        try:
            result = await prediction_port.predict_ctr(
                cover_features=cover_features,
                title=title,
                platform=platform,
            )
            ctr_pct = result.ctr * 100
            factors = result.factors or {}
            report = f"""【CTR 预估】
预估点击率：{ctr_pct:.2f}%
置信度：{result.confidence:.0%}
因子贡献：{', '.join(f'{k}:{v:.0%}' for k, v in factors.items()) if factors else '暂无'}"""
            return {"analysis": {**existing, "ctr_prediction": report}}
        except Exception as e:
            logger.warning("CTR 预测失败: %s", e)
            return {"analysis": {**existing, "ctr_prediction": FALLBACK}}

    plugin_center.register_plugin(
        "ctr_prediction",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

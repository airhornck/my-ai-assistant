"""
爆款预测插件：分析脑实时插件。
内容特征 → 爆款概率、流量区间预估。
依赖：prediction_port；可选 video_decomposition_port、analysis（已有拆解结果）作为特征输入。
"""
from __future__ import annotations

import logging
from typing import Any

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

FALLBACK = """【爆款预测】
爆款概率：65%
（prediction_port 未配置时使用兜底）"""


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """注册爆款预测插件。"""
    prediction_port = config.get("prediction_port")
    decomposition_port = config.get("video_decomposition_port")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        existing = context.get("analysis") or {}
        if not isinstance(existing, dict):
            existing = {}
        pi = context.get("plugin_input") or {}
        platform = pi.get("platform", "") or "default"

        features = {}
        # 若已有 video_viral_structure，可解析后作为特征（简化：用 analysis 中的结构化字段）
        if existing.get("video_viral_structure"):
            features["structure_text"] = str(existing["video_viral_structure"])[:500]
        # 若有拆解端口且提供了 video_url，可调用拆解
        if decomposition_port and pi.get("video_url"):
            try:
                struct = await decomposition_port.decompose(
                    video_url=pi["video_url"],
                    raw_text=pi.get("script", ""),
                    platform=platform,
                )
                features["opening_style"] = struct.opening_style
                features["turning_points_count"] = len(struct.turning_points)
                features["duration_sec"] = struct.duration_sec
                features["structure"] = struct.to_dict()
            except Exception as e:
                logger.debug("爆款预测：拆解失败 %s", e)

        if not features:
            req = context.get("request")
            topic = getattr(req, "topic", "") or ""
            product = getattr(req, "product_desc", "") or ""
            features["topic"] = f"{topic} {product}".strip()[:200] or "通用"

        if not prediction_port:
            return {"analysis": {**existing, "viral_prediction": FALLBACK}}

        try:
            result = await prediction_port.predict_viral(features=features, platform=platform)
            score_pct = result.score * 100
            factors = result.factors or {}
            report = f"""【爆款预测】
爆款概率：{score_pct:.1f}%
置信度：{result.confidence:.0%}
因子贡献：{', '.join(f'{k}:{v:.0%}' for k, v in factors.items()) if factors else '暂无'}"""
            return {"analysis": {**existing, "viral_prediction": report}}
        except Exception as e:
            logger.warning("爆款预测失败: %s", e)
            return {"analysis": {**existing, "viral_prediction": FALLBACK}}

    plugin_center.register_plugin(
        "viral_prediction",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

"""
封面诊断插件：分析脑实时插件。
参考 Veogo AI：画面构图与画质提升。
主体、配色、布局、违规检测、CTR 关联建议。
依赖：multimodal_port、prediction_port（按需）。
"""
from __future__ import annotations

import logging
from typing import Any

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

FALLBACK = """【封面诊断】
主体：待分析
配色：待分析
布局：待分析
（multimodal_port 未配置时使用兜底）"""


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """注册封面诊断插件。"""
    multimodal_port = config.get("multimodal_port")
    prediction_port = config.get("prediction_port")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        existing = context.get("analysis") or {}
        if not isinstance(existing, dict):
            existing = {}
        pi = context.get("plugin_input") or {}
        cover_url = pi.get("cover_url", "")
        platform = pi.get("platform", "") or "default"

        if not cover_url:
            return {"analysis": {**existing, "cover_diagnosis": "【封面诊断】未提供封面 URL，请传入 plugin_input.cover_url"}}

        if not multimodal_port:
            return {"analysis": {**existing, "cover_diagnosis": FALLBACK}}

        try:
            img_result = await multimodal_port.analyze_image(cover_url)
            lines = [
                "【封面诊断】",
                f"主体：{img_result.subject or '未识别'}",
                f"配色：{', '.join(img_result.color_palette) if img_result.color_palette else '未识别'}",
                f"布局：{img_result.layout or '未识别'}",
                f"有文字：{'是' if img_result.has_text else '否'}",
                f"情绪标签：{', '.join(img_result.mood_tags) if img_result.mood_tags else '无'}",
            ]
            if img_result.violation_detected:
                lines.append(f"⚠ 违规检测：{', '.join(img_result.violation_tags)}")
            if img_result.text_content:
                lines.append(f"文字内容：{img_result.text_content[:80]}...")

            # 可选：CTR 预估
            ctr_suggestion = ""
            if prediction_port:
                try:
                    ctr_result = await prediction_port.predict_ctr(
                        cover_features=img_result.to_dict(),
                        title="",
                        platform=platform,
                    )
                    ctr_pct = ctr_result.ctr * 100
                    ctr_suggestion = f"\n预估点击率：{ctr_pct:.2f}%"
                except Exception as e:
                    logger.debug("封面诊断：CTR 预估失败 %s", e)
            lines.append(ctr_suggestion.strip() or "")

            report = "\n".join(l for l in lines if l)
            return {"analysis": {**existing, "cover_diagnosis": report}}
        except Exception as e:
            logger.warning("封面诊断失败: %s", e)
            return {"analysis": {**existing, "cover_diagnosis": FALLBACK}}

    plugin_center.register_plugin(
        "cover_diagnosis",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

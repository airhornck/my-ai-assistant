"""
视频爆款结构拆解插件：分析脑实时插件。
参考 Veogo AI：开场3秒吸睛、转折点、BGM情绪曲线、剪辑节奏、时长分布。
依赖：video_decomposition_port（按需调用）。
"""
from __future__ import annotations

import logging
from typing import Any

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

FALLBACK = """【视频爆款结构拆解】
开场：直接点题 / 悬念 / 画面冲击
转折点：15-30秒处内容切换，45-60秒处情绪提升
BGM：前段吸引、中段讲解、结尾互动
时长分布：前3秒吸睛占5%，前15秒钩子占25%
（video_decomposition 未配置时使用兜底）"""


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """注册视频爆款结构拆解插件。"""
    decomposition_port = config.get("video_decomposition_port")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        existing = context.get("analysis") or {}
        if not isinstance(existing, dict):
            existing = {}
        pi = context.get("plugin_input") or {}
        video_url = pi.get("video_url", "")
        platform = pi.get("platform", "") or (getattr(context.get("request"), "topic", "") or "default")
        raw_text = pi.get("script", "") or ""

        if not decomposition_port:
            return {"analysis": {**existing, "video_viral_structure": FALLBACK}}

        try:
            struct = await decomposition_port.decompose(
                video_url=video_url,
                raw_text=raw_text,
                platform=platform,
            )
            report = _format_report(struct)
            return {"analysis": {**existing, "video_viral_structure": report}}
        except Exception as e:
            logger.warning("视频爆款结构拆解失败: %s", e)
            return {"analysis": {**existing, "video_viral_structure": FALLBACK}}

    def _format_report(s) -> str:
        lines = ["【视频爆款结构拆解】"]
        if s.opening_style:
            lines.append(f"开场方式：{s.opening_style}")
        if s.opening_hooks:
            lines.append(f"开场 hooks：{', '.join(s.opening_hooks)}")
        if s.turning_points:
            pts = [f"{p.get('timestamp', '')}s {p.get('desc', '')}" for p in s.turning_points]
            lines.append(f"转折点：{' | '.join(pts)}")
        if s.bgm_emotion_curve:
            curve = [f"{c.get('start', 0)}-{c.get('end', 0)}s {c.get('emotion', '')}" for c in s.bgm_emotion_curve]
            lines.append(f"BGM 情绪曲线：{' | '.join(curve)}")
        if s.duration_distribution:
            dist = ", ".join(f"{k}:{v}" for k, v in s.duration_distribution.items())
            lines.append(f"时长分布：{dist}")
        if s.call_to_action:
            lines.append(f"行动召唤：{s.call_to_action}")
        return "\n".join(lines) if len(lines) > 1 else FALLBACK

    plugin_center.register_plugin(
        "video_viral_structure",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

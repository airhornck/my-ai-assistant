"""
视频生成插件：生成脑占位插件，待接入具体模型后实现。
模型配置由插件中心 config["models"]["video_generator"] 管理。
"""
from __future__ import annotations

import logging
from typing import Any

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

PLACEHOLDER = "（视频生成能力待实现，请先配置 generation_video 接口与插件）"


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """向生成脑插件中心注册视频生成占位插件。"""
    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """占位：返回提示文案。"""
        return {"content": PLACEHOLDER}

    plugin_center.register_plugin(
        "video_generator",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )

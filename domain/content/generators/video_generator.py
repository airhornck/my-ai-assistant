"""
视频生成模块（占位）：待接入文生视频等模型接口。
配置从 config.api_config 的 generation_video 接口获取。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class VideoGenerator:
    """视频生成模块（占位）。"""

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        if self._config:
            logger.info("VideoGenerator 已初始化, model=%s", self._config.get("model", "未配置"))
        else:
            logger.debug("VideoGenerator 占位，未配置模型")

    async def generate(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        """生成视频。当前未实现，返回占位提示。"""
        return "[视频生成模块待接入，请配置 GENERATOR_VIDEO_MODEL、GENERATOR_VIDEO_API_KEY]"

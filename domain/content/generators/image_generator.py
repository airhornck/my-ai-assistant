"""
图片生成模块（占位）：待接入文生图等模型接口。
配置从 config.api_config 的 generation_image 接口获取。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ImageGenerator:
    """图片生成模块（占位）。"""

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        if self._config:
            logger.info("ImageGenerator 已初始化, model=%s", self._config.get("model", "未配置"))
        else:
            logger.debug("ImageGenerator 占位，未配置模型")

    async def generate(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        """生成图片。当前未实现，返回占位提示。"""
        return "[图片生成模块待接入，请配置 GENERATOR_IMAGE_MODEL、GENERATOR_IMAGE_API_KEY]"

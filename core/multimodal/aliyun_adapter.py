"""
多模态阿里云适配器：对接阿里云视频理解 / 视觉 API。
未配置 Key 时行为等同 Mock。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from core.multimodal.port import IMultimodalPort, ImageAnalysisResult, VideoAnalysisResult

logger = logging.getLogger(__name__)


class AliyunMultimodalAdapter(IMultimodalPort):
    """
    阿里云多模态实现。
    可对接：通义千问-VL、视觉智能开放平台等。
    当前为占位实现，返回 Mock 结构；接入真实 API 时替换内部逻辑。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self._api_key = (api_key or os.getenv("DASHSCOPE_API_KEY", "")).strip()
        self._base_url = base_url or os.getenv("DASHSCOPE_BASE_URL", "")

    async def analyze_image(
        self,
        url: str | bytes,
        *,
        options: Optional[dict[str, Any]] = None,
    ) -> ImageAnalysisResult:
        if not self._api_key:
            logger.info("阿里云多模态 API Key 未配置，使用 Mock 返回")
            return await self._mock_image()
        try:
            # TODO: 接入阿里云视觉/通义千问-VL API
            # 示例：https://help.aliyun.com/zh/model-studio/developer-reference/qwen-vl-plus
            logger.warning("阿里云多模态 analyze_image 暂未接入，返回 Mock")
            return await self._mock_image()
        except Exception as e:
            logger.warning("阿里云多模态 analyze_image 失败: %s，降级 Mock", e)
            return await self._mock_image()

    async def analyze_video(
        self,
        url: str,
        *,
        options: Optional[dict[str, Any]] = None,
    ) -> VideoAnalysisResult:
        if not self._api_key:
            logger.info("阿里云多模态 API Key 未配置，使用 Mock 返回")
            return await self._mock_video()
        try:
            # TODO: 接入阿里云视频理解 API
            logger.warning("阿里云多模态 analyze_video 暂未接入，返回 Mock")
            return await self._mock_video()
        except Exception as e:
            logger.warning("阿里云多模态 analyze_video 失败: %s，降级 Mock", e)
            return await self._mock_video()

    async def _mock_image(self) -> ImageAnalysisResult:
        return ImageAnalysisResult(
            subject="（阿里云占位）封面主体",
            color_palette=[],
            has_text=False,
            text_content="",
            layout="",
            mood_tags=[],
            violation_detected=False,
            violation_tags=[],
            raw={"source": "aliyun_placeholder"},
        )

    async def _mock_video(self) -> VideoAnalysisResult:
        return VideoAnalysisResult(
            keyframes=[],
            emotion_curve=[],
            violation_detected=False,
            violation_timestamps=[],
            duration_sec=0.0,
            resolution="",
            raw={"source": "aliyun_placeholder"},
        )

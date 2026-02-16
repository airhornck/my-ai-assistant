"""
多模态 Mock 适配器：开发/测试用，无外部调用。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from core.multimodal.port import IMultimodalPort, ImageAnalysisResult, VideoAnalysisResult

logger = logging.getLogger(__name__)


class MockMultimodalAdapter(IMultimodalPort):
    """Mock 实现：返回固定结构，不调用外部 API。"""

    async def analyze_image(
        self,
        url: str | bytes,
        *,
        options: Optional[dict[str, Any]] = None,
    ) -> ImageAnalysisResult:
        logger.debug("Mock 多模态: analyze_image(url=%s)", str(url)[:80] if isinstance(url, str) else "<bytes>")
        return ImageAnalysisResult(
            subject="（Mock）封面主体",
            color_palette=["#FF5733", "#33FF57"],
            has_text=True,
            text_content="（Mock）封面文字",
            layout="居中",
            mood_tags=["轻松", "吸睛"],
            violation_detected=False,
            violation_tags=[],
            raw={"source": "mock"},
        )

    async def analyze_video(
        self,
        url: str,
        *,
        options: Optional[dict[str, Any]] = None,
    ) -> VideoAnalysisResult:
        logger.debug("Mock 多模态: analyze_video(url=%s)", url[:80] if url else "")
        return VideoAnalysisResult(
            keyframes=[
                {"timestamp": 0, "description": "（Mock）开场"},
                {"timestamp": 30, "description": "（Mock）中间转折"},
            ],
            emotion_curve=[
                {"start": 0, "end": 15, "emotion": "吸引"},
                {"start": 15, "end": 45, "emotion": "讲解"},
            ],
            violation_detected=False,
            violation_timestamps=[],
            duration_sec=60.0,
            resolution="1920x1080",
            raw={"source": "mock"},
        )

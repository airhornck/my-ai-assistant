"""
视频拆解 Mock 适配器：基于规则/LLM 占位，无多模态调用。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from models.video_content_schema import VideoContentStructure
from services.video_decomposition.port import IVideoDecompositionPort

logger = logging.getLogger(__name__)


class MockVideoDecompositionAdapter(IVideoDecompositionPort):
    """Mock 实现：返回固定结构。可扩展为基于 LLM 的拆解。"""

    async def decompose(
        self,
        video_url: str = "",
        *,
        raw_text: str = "",
        multimodal_result: Optional[dict[str, Any]] = None,
        platform: str = "",
    ) -> VideoContentStructure:
        logger.debug("Mock 拆解: platform=%s, has_url=%s", platform, bool(video_url))
        return VideoContentStructure(
            opening_style="直接点题",
            opening_hooks=["（Mock）开篇吸睛"],
            turning_points=[
                {"timestamp": 15, "desc": "（Mock）第一个转折", "type": "内容切换"},
            ],
            bgm_emotion_curve=[
                {"start": 0, "end": 20, "emotion": "吸引"},
                {"start": 20, "end": 60, "emotion": "讲解"},
            ],
            duration_distribution={"hook_3s": 0.05, "hook_15s": 0.25},
            call_to_action="点赞关注",
            extra={"source": "mock"},
            platform=platform,
            video_id="",
            duration_sec=60.0,
        )

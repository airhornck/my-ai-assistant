"""
视频结构化拆解 Port：输入原始内容，输出 VideoContentStructure。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from models.video_content_schema import VideoContentStructure


class IVideoDecompositionPort(ABC):
    """视频结构化拆解端口。"""

    @abstractmethod
    async def decompose(
        self,
        video_url: str = "",
        *,
        raw_text: str = "",
        multimodal_result: Optional[dict[str, Any]] = None,
        platform: str = "",
    ) -> VideoContentStructure:
        """
        将视频/脚本拆解为结构化内容。
        :param video_url: 视频 URL（可选，有则调用多模态分析）
        :param raw_text: 文案/脚本原文
        :param multimodal_result: 若已有 multimodal 分析结果可传入，避免重复调用
        :param platform: 平台标识
        :return: 结构化输出
        """
        ...

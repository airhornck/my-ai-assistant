"""
多模态内容理解 Port：图像/视频分析接口抽象。
实现者可替换为阿里云视频理解 API、开源模型等。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ImageAnalysisResult:
    """封面/图像分析结果。"""

    # 视觉元素
    subject: str = ""  # 主体描述
    color_palette: list[str] = field(default_factory=list)  # 主色
    has_text: bool = False
    text_content: str = ""
    layout: str = ""  # 如 居中/三分法

    # 情绪/氛围
    mood_tags: list[str] = field(default_factory=list)  # 如 轻松、紧张、专业

    # 违规相关
    violation_detected: bool = False
    violation_tags: list[str] = field(default_factory=list)

    # 原始扩展
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "color_palette": self.color_palette,
            "has_text": self.has_text,
            "text_content": self.text_content,
            "layout": self.layout,
            "mood_tags": self.mood_tags,
            "violation_detected": self.violation_detected,
            "violation_tags": self.violation_tags,
            "raw": self.raw,
        }


@dataclass
class VideoAnalysisResult:
    """视频分析结果。"""

    # 关键帧/场景
    keyframes: list[dict[str, Any]] = field(default_factory=list)  # [{timestamp, description, ...}]

    # 情绪曲线（按时间段）
    emotion_curve: list[dict[str, Any]] = field(default_factory=list)  # [{start, end, emotion}]

    # 违规
    violation_detected: bool = False
    violation_timestamps: list[float] = field(default_factory=list)

    # 时长、分辨率等元数据
    duration_sec: float = 0.0
    resolution: str = ""

    # 原始扩展
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyframes": self.keyframes,
            "emotion_curve": self.emotion_curve,
            "violation_detected": self.violation_detected,
            "violation_timestamps": self.violation_timestamps,
            "duration_sec": self.duration_sec,
            "resolution": self.resolution,
            "raw": self.raw,
        }


class IMultimodalPort(ABC):
    """多模态内容理解端口。"""

    @abstractmethod
    async def analyze_image(
        self,
        url: str | bytes,
        *,
        options: Optional[dict[str, Any]] = None,
    ) -> ImageAnalysisResult:
        """
        分析图像/封面。
        :param url: 图片 URL 或 bytes
        :param options: 可选配置，如 {"check_violation": True}
        :return: 结构化分析结果
        """
        ...

    @abstractmethod
    async def analyze_video(
        self,
        url: str,
        *,
        options: Optional[dict[str, Any]] = None,
    ) -> VideoAnalysisResult:
        """
        分析视频。
        :param url: 视频 URL
        :param options: 可选，如 {"extract_keyframes": True, "max_frames": 10}
        :return: 结构化分析结果
        """
        ...

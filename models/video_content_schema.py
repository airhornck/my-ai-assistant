"""
视频内容结构化 Schema：供拆解插件统一输出，为预测模型提供训练数据。
支持版本化扩展。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0"


@dataclass
class VideoContentStructure:
    """视频内容结构化输出。"""

    # 开场方式
    opening_style: str = ""  # 如 悬念/直接点题/画面冲击
    opening_hooks: list[str] = field(default_factory=list)  # 具体 hooks

    # 转折点（时间戳 + 描述）
    turning_points: list[dict[str, Any]] = field(default_factory=list)  # [{timestamp, desc, type}]

    # BGM 情绪曲线（按时间段）
    bgm_emotion_curve: list[dict[str, Any]] = field(default_factory=list)  # [{start, end, emotion}]

    # 时长分布（如 前3秒/前15秒/总时长占比）
    duration_distribution: dict[str, float] = field(default_factory=dict)

    # 行动召唤
    call_to_action: str = ""  # 如 点赞/关注/评论区

    # 扩展字段
    extra: dict[str, Any] = field(default_factory=dict)

    # 元数据
    platform: str = ""
    video_id: str = ""
    duration_sec: float = 0.0
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "opening_style": self.opening_style,
            "opening_hooks": self.opening_hooks,
            "turning_points": self.turning_points,
            "bgm_emotion_curve": self.bgm_emotion_curve,
            "duration_distribution": self.duration_distribution,
            "call_to_action": self.call_to_action,
            "extra": self.extra,
            "platform": self.platform,
            "video_id": self.video_id,
            "duration_sec": self.duration_sec,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VideoContentStructure":
        return cls(
            opening_style=d.get("opening_style", ""),
            opening_hooks=d.get("opening_hooks", []) or [],
            turning_points=d.get("turning_points", []) or [],
            bgm_emotion_curve=d.get("bgm_emotion_curve", []) or [],
            duration_distribution=d.get("duration_distribution", {}) or {},
            call_to_action=d.get("call_to_action", ""),
            extra=d.get("extra", {}) or {},
            platform=d.get("platform", ""),
            video_id=d.get("video_id", ""),
            duration_sec=float(d.get("duration_sec", 0)),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )

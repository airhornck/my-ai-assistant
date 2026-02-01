"""
生成脑模块配置：兼容层，统一从 config.api_config 读取。
文本/图片/视频配置均来自 api_config 的 LLM_INTERFACES (generation_text/image/video)。
"""
from __future__ import annotations

from typing import Any, Optional

# 统一接口配置入口：config/api_config
from config.api_config import get_model_config, MODEL_ROLES

# 输出类型枚举
OUTPUT_TYPE_TEXT = "text"
OUTPUT_TYPE_IMAGE = "image"
OUTPUT_TYPE_VIDEO = "video"


def _role_ready(role: str) -> bool:
    return bool((MODEL_ROLES.get(role) or {}).get("model", "").strip())


def get_generator_text_config() -> dict[str, Any]:
    """文本生成配置，来自 api_config.generation_text。"""
    return get_model_config("generation_text")


def get_generator_image_config() -> Optional[dict[str, Any]]:
    """图片生成配置，来自 api_config.generation_image。未配置时返回 None。"""
    if not _role_ready("generation_image"):
        return None
    return get_model_config("generation_image")


def get_generator_video_config() -> Optional[dict[str, Any]]:
    """视频生成配置，来自 api_config.generation_video。未配置时返回 None。"""
    if not _role_ready("generation_video"):
        return None
    return get_model_config("generation_video")
